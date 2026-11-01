"""Required tools: did the agent call every tool its instructions make mandatory on this ticket?

Example: RITM0011059's source is 0.0.0.0/0. An agent that stops with the right
reason but never looks that source up is marked skipped_tool and fails the ticket.

Why: a right answer reached by skipping a required check can be luck, and the
outcome scorers cannot see that. This one reads what the agent actually called.

Safety rule: the answer key is read here only to score, after the agent replied.
Four rules, each from the instructions the agent is given:

1. Drafter step 1: on any ticket but a removal, look up every source and destination
   given as a CIDR or IP group. Only `*` is exempt, because the tool refuses it. This
   rule wins over a label's shorter `tools:` list.
2. RB-01-1, RB-02-1, RB-03-1: duplicate_rule_check at each env-site the label's `tools:` names.
3. RB-02-3: dnat_port_check at each env-site of a labelled DNAT rule.
4. RB-01-6: dns_lookup_for_fqdn when the label's `tools:` lists it.
"""

from __future__ import annotations

import ipaddress

LOCATE = "locate_address_for_env_site"
DUPLICATE = "duplicate_rule_check"
DNAT_PORT = "dnat_port_check"
DNS = "dns_lookup_for_fqdn"
REMOVAL = "Firewall Rule Removal"
REFUSED_BY_TOOL = "*"


def _address(text) -> str:
    """One address in a form that compares: 10.0.0.1 and 10.0.0.1/32 are the same; a group name stays as written."""
    try:
        return str(ipaddress.IPv4Network(str(text).strip(), strict=False))
    except ValueError:
        return str(text).strip()


def _lookups_required(ticket: dict) -> list[str]:
    """Every source and destination step 1 says to look up, in ticket order; none on a removal."""
    if ticket.get("item") == REMOVAL:
        return []
    entries = ticket.get("sources", []) + ticket.get("destination", [])
    values = [entry.get("cidr") or entry.get("ip_group") for entry in entries]
    return [value for value in values if value and value != REFUSED_BY_TOOL]


def missing_tools(ticket: dict, expected: dict, tool_calls: list[dict]) -> list[str]:
    """Each required tool call the agent did not make; [] when it made them all."""
    def called(tool: str, field: str | None = None) -> set[str]:
        """The values of one argument across calls to one tool, or the tool's name if it was called at all."""
        calls = [c for c in tool_calls if c.get("name") == tool]
        return {_address(c.get("arguments", {}).get(field)) for c in calls} if field else {tool} & {c.get("name") for c in calls}

    located = called(LOCATE, "address")
    missing = [f"{LOCATE} {value}" for value in _lookups_required(ticket) if _address(value) not in located]
    labelled = expected.get("tools") or []
    sites = called(DUPLICATE, "env_site")
    missing += [f"{DUPLICATE} {t['env_site']}" for t in labelled if t.get("tool") == DUPLICATE and t["env_site"] not in sites]
    ports = called(DNAT_PORT, "env_site")
    wanted = dict.fromkeys(r["env_site"] for r in expected.get("rules") or [] if r.get("translated_address"))
    missing += [f"{DNAT_PORT} {site}" for site in wanted if site not in ports]
    if any(t.get("tool") == DNS for t in labelled) and not called(DNS):
        missing.append(DNS)
    return missing
