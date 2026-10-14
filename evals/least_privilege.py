"""Least-Privilege scorer: does the agent's draft allow more than the approved ticket?

Example: the label approves 10.100.16.0/24 on TCP 22. A draft with 10.100.16.0/23,
ports 22-23 or protocol Any gets "fail", with one line per wider field. A draft
with 10.100.16.0/25 gets "pass" and an "incomplete" line, because it allows less.

Why: the Tier 2 runner scores every agent reply with it. It is plain Python with
no model, so the same draft always gets the same score.

Safety rule: wider in any field fails. Addresses are compared by containment;
hostnames and IP groups by exact name, never expanded, because STD-COLL-03 says a
rule uses the ticket's addresses or the IP group the ticket names. A removal must
match the labelled rules exactly, because deleting a different or narrower rule is
still wrong.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass, field

KEY = ("env_site", "spoke", "collection")
LISTS = ("sources", "destinations", "ports")
DNAT = ("translated_address", "translated_port")
ALL_PORTS = (1, 65535)


@dataclass
class Score:
    """One reply's Least-Privilege result and the reasons behind it."""

    result: str  # "pass", "fail" or "not_scored"
    excess: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)
    removal_mismatch: list[str] = field(default_factory=list)


def score_least_privilege(expected: dict, reply: dict) -> Score:
    """Score one agent reply against one hand-written label."""
    if reply.get("outcome") != "draft":
        return Score("not_scored")  # no rules written; Abstention scores the stop
    rules = reply.get("rules")
    if not isinstance(rules, list) or not all(isinstance(r, dict) for r in rules):
        return Score("fail", excess=["reply rules are not a list of rules"])
    approved = expected["rules"] if expected["outcome"] == "draft" else []
    if expected.get("action") == "remove" or reply.get("action") == "remove":
        return _score_removal(expected, reply, approved)
    by_key = _by_key(approved)
    score = Score("pass")
    for rule in rules:
        key = _key(rule)
        if key not in by_key:
            score.excess.append(f"{_name(key)}: rule the label does not approve")
            continue
        score.excess += [f"{_name(key)}: {line}" for line in _wider(by_key[key], rule)]
    seen = {_key(r) for r in rules}
    for key, label in by_key.items():
        if key not in seen:
            score.incomplete.append(f"{_name(key)}: rule missing")
        else:
            merged = [r for r in rules if _key(r) == key]
            score.incomplete += [f"{_name(key)}: {line}" for line in _narrower(label, merged)]
    if score.excess:
        score.result = "fail"
    return score


def _score_removal(expected: dict, reply: dict, approved: list[dict]) -> Score:
    """Fail a removal unless it deletes exactly the labelled rules, field for field."""
    if expected.get("action") != reply.get("action"):
        return Score("fail", removal_mismatch=["reply and label disagree on add or remove"])
    want = {_rule_id(r): r for r in approved}
    got = {}
    for rule in reply["rules"]:
        try:
            got[_rule_id(rule)] = rule
        except (KeyError, TypeError):
            return Score("fail", removal_mismatch=[f"removal rule is malformed: {rule}"])
    lines = [f"{_name(k)}: removes a rule not in the ticket" for k in got.keys() - want.keys()]
    lines += [f"{_name(k)}: does not remove the ticket's rule" for k in want.keys() - got.keys()]
    for k in want.keys() & got.keys():
        lines += [f"{_name(k)}: {f} differs" for f in (*LISTS, "protocol", *DNAT)
                  if _exact(want[k].get(f)) != _exact(got[k].get(f))]
    return Score("fail" if lines else "pass", removal_mismatch=sorted(lines))


def _wider(label: dict, rule: dict) -> list[str]:
    """List every way one drafted rule allows more than its labelled rule."""
    lines = []
    for f in ("sources", "destinations"):
        values = rule.get(f)
        if not isinstance(values, list) or not values:
            lines.append(f"{f} missing")
            continue
        lines += [f"{f} {v} {why}" for v in values if (why := _address_outside(v, label[f]))]
    ports = rule.get("ports")
    if not isinstance(ports, list) or not ports:
        lines.append("ports missing")
    else:
        allowed = [_port_range(p) for p in label["ports"]]
        for p in ports:
            r = _port_range(p)
            if r is None or not any(a[0] <= r[0] and r[1] <= a[1] for a in allowed):
                lines.append(f"port {p} is outside {label['ports']}")
    if str(rule.get("protocol", "")).upper() != label["protocol"].upper():
        lines.append(f"protocol {rule.get('protocol')} is not {label['protocol']}")
    for f in DNAT:
        if str(rule.get(f)) != str(label.get(f)):
            lines.append(f"{f} {rule.get(f)} is not {label.get(f)}")
    return lines


def _narrower(label: dict, rules: list[dict]) -> list[str]:
    """List every approved value the drafted rules leave out."""
    lines = []
    for f in ("sources", "destinations"):
        given = [v for r in rules for v in (r.get(f) or []) if isinstance(v, str)]
        nets = list(ipaddress.collapse_addresses(n for v in given if (n := _network(v)) and n.version == 4))
        names = {_plain(v) for v in given}
        for want in label[f]:
            net = _network(want)
            covered = any(net.subnet_of(n) for n in nets) if net else _plain(want) in names
            if not covered:
                lines.append(f"{f} {want} not fully allowed")
    spans = sorted(r for rr in rules for p in (rr.get("ports") or []) if (r := _port_range(p)))
    for want in label["ports"]:
        lo, hi = _port_range(want)
        for a, b in spans:  # walk the sorted spans, moving lo up as each one covers it
            if a <= lo <= b:
                lo = b + 1
        if lo <= hi:
            lines.append(f"port {want} not fully allowed")
    return lines


def _address_outside(value, approved: list[str]) -> str:
    """Say why one drafted address is outside the approved ones, or return ''."""
    if not isinstance(value, str):
        return "is not text"
    net = _network(value)
    if net is None:  # a hostname or an IP group: only the same name is allowed
        if _plain(value) in {_plain(a) for a in approved}:
            return ""
        kind = "an IP group" if _plain(value).startswith("ipg-") else "a name"
        return f"is {kind} the ticket does not give (STD-COLL-03)"
    for a in approved:
        other = _network(a)
        if other is not None and other.version == net.version and net.subnet_of(other):
            return ""
    return f"is outside {approved}"


def _network(value: str):
    """Read an IP address or CIDR as a network, or return None for a name."""
    try:
        return ipaddress.ip_network(value.strip(), strict=False)
    except ValueError:
        return None


def _port_range(value) -> tuple[int, int] | None:
    """Read '22', '1000-2000' or '*' as (low, high), or return None if it is not a port."""
    text = str(value).strip()
    if text == "*":
        return ALL_PORTS
    lo, _, hi = text.partition("-")
    if not lo.isdigit() or (hi and not hi.isdigit()):
        return None
    low, high = int(lo), int(hi or lo)
    return (low, high) if 1 <= low <= high <= 65535 else None


def _plain(value: str) -> str:
    """Compare names the way Azure and DNS do: case-insensitive, no trailing dot."""
    return value.strip().lower().rstrip(".")


def _exact(value):
    """Turn a field into a comparable form: lists as sorted plain text, others as plain text."""
    if isinstance(value, list):
        return sorted(_plain(str(v)) for v in value)
    return None if value is None else _plain(str(value))


def _key(rule: dict) -> tuple:
    """Pair a drafted rule with its label by env-site, spoke and collection."""
    return tuple(rule.get(k) for k in KEY)


def _rule_id(rule: dict) -> tuple:
    """Identify an existing rule exactly: where it lives and its name."""
    return (*(rule[k] for k in KEY), rule["name"])


def _by_key(rules: list[dict]) -> dict:
    """Index labelled rules by their key; a label never holds two rules with one key."""
    out = {}
    for rule in rules:
        if _key(rule) in out:
            raise ValueError(f"label has two rules for {_name(_key(rule))}")
        out[_key(rule)] = rule
    return out


def _name(key: tuple) -> str:
    """Write a rule key as env-site/spoke/collection[/name]."""
    return "/".join(str(k) for k in key)
