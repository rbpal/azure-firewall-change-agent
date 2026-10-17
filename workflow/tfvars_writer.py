"""Insert one drafted rule into a spoke's rules file as text, changing nothing else.

Example: a draft for `https-sett-to-northwindFs` in prod-eastus2 becomes the entry
"024-https-sett-to-northwindFs" at the end of `allow-sett-network-rules` in
infra/envs/prod-eastus2/firewall_policy_rule_collection_groups/sett.tfvars.

Why: the agent returns JSON and never writes a file. Code builds the path from the
known env-sites and spokes, picks the index (rule_index.py) and writes the entry in
the layout `terraform fmt` produces, so the engineer reviews a clean one-entry diff.

Safety rule: an unknown env-site or spoke, a collection that does not match the
rule type, a malformed name, a name already in the collection, or a value that
could break out of an HCL string is refused. After the insert the file is parsed
again: the new rule must be there with the drafted fields, and every other rule
must be unchanged.
"""

from __future__ import annotations

import ipaddress
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "mcp"))

from data_readers.read_addressplan_routing import LocalSource, load_hubs  # noqa: E402
from data_readers.read_env_site_ipgroup import RULES_FILE, parse_rules  # noqa: E402

from workflow.rule_index import collection_name, next_index  # noqa: E402

NAME = re.compile(r"^[a-z0-9]+-[a-z]+-to-[a-z][a-zA-Z0-9]+$")  # STD-NAME-03, without the index
SAFE = re.compile(r"^[A-Za-z0-9.:/*_-]+$")  # no quotes, spaces, braces, $ or backslashes
FQDN = re.compile(r"^(\*\.)?([a-z0-9-]+\.)+[a-z]{2,}$")
APP_PROTOCOLS = {"HTTP": "Http", "HTTPS": "Https"}
ENTRY_INDENT = " " * 8  # rule keys sit at 8 spaces inside `rules = {`


class DraftError(ValueError):
    """The draft cannot be written as it is; the workflow stops and tells the engineer."""


def rule_type(draft: dict) -> str:
    """Tell the rule type from the draft's fields: translation means DNAT, HTTP(S) means application."""
    if "translated_address" in draft:
        return "dnat"
    return "application" if str(draft.get("protocol", "")).upper() in APP_PROTOCOLS else "network"


def _safe(values: list, field: str) -> list[str]:
    """Check each value is a plain token that cannot break out of an HCL string."""
    if not isinstance(values, list) or not values:
        raise DraftError(f"{field} must be a non-empty list")
    out = [str(v) for v in values]
    for v in out:
        if not SAFE.match(v):
            raise DraftError(f"{field} value {v!r} has characters a rule never needs")
    return out


def _is_address(value: str) -> bool:
    """True for an IP address or CIDR."""
    try:
        ipaddress.ip_network(value, strict=True)
        return True
    except ValueError:
        return False


def _split(values: list[str], side: str, allow_fqdn: bool) -> dict[str, list[str]]:
    """Sort addresses, IP groups and hostnames into the tfvars fields they belong in."""
    fields: dict[str, list[str]] = {}
    for v in values:
        if v.startswith("ipg-"):
            key = f"{side}_ip_groups"
        elif _is_address(v):
            key = f"{side}_addresses"
        elif allow_fqdn and FQDN.match(v):
            key = f"{side}_fqdns"
        else:
            raise DraftError(f"{side} {v!r} is not an address, CIDR, IP group or allowed hostname")
        fields.setdefault(key, []).append(v)
    return fields


def rule_fields(draft: dict) -> dict:
    """Turn the agent's draft into the rule's tfvars fields, in the order the repo's files use."""
    kind = rule_type(draft)
    name = str(draft.get("name", ""))
    if not NAME.match(name):
        raise DraftError(f"rule name {name!r} does not follow STD-NAME-03 (<service>-<source>-to-<destination>)")
    sources = _split(_safe(draft.get("sources"), "sources"), "source", allow_fqdn=False)
    destinations = _safe(draft.get("destinations"), "destinations")
    ports = _safe(draft.get("ports"), "ports")
    protocol = str(draft.get("protocol", "")).upper()
    if kind == "dnat":
        if len(destinations) != 1 or not _is_address(destinations[0]):
            raise DraftError("a DNAT rule needs exactly one destination: the firewall's public IP")
        translated = _safe([draft.get("translated_address"), draft.get("translated_port")], "translation")
        return {"name": name, "protocols": [protocol], **sources, "destination_address": destinations[0],
                "destination_ports": ports, "translated_address": translated[0], "translated_port": translated[1]}
    if kind == "application":
        return {"name": name, "protocols": [f"{APP_PROTOCOLS[protocol]}:{p}" for p in ports], **sources,
                **_split(destinations, "destination", allow_fqdn=True)}
    if protocol not in {"TCP", "UDP", "ICMP", "ANY"}:
        raise DraftError(f"network protocol {protocol!r} is not TCP, UDP, ICMP or Any")
    return {"name": name, "protocols": ["Any" if protocol == "ANY" else protocol], **sources,
            **_split(destinations, "destination", allow_fqdn=True), "destination_ports": ports}


def _hcl_value(value) -> str:
    """Render a string or list of strings the way terraform fmt writes them."""
    if isinstance(value, list):
        return "[" + ", ".join(f'"{v}"' for v in value) + "]"
    return f'"{value}"'


def render_entry(key: str, fields: dict) -> str:
    """Render one rule entry, with its = signs aligned as terraform fmt aligns them."""
    width = max(len(k) for k in fields)
    lines = [f'{ENTRY_INDENT}"{key}" = {{']
    lines += [f"{ENTRY_INDENT}  {k.ljust(width)} = {_hcl_value(v)}" for k, v in fields.items()]
    lines.append(f"{ENTRY_INDENT}}}")
    return "\n".join(lines) + "\n"


def _rules_close(lines: list[str], collection: str, path: str) -> int:
    """Find the line that closes the collection's `rules = {` block."""
    try:
        start = lines.index(f"    {collection} = {{\n")
        rules = lines.index("      rules = {\n", start)
        return lines.index("      }\n", rules)
    except ValueError:
        raise DraftError(f"{path}: collection {collection} not found in the layout terraform fmt writes") from None


def insert_rule(text: str, spoke: str, draft: dict, index: str, path: str = "<tfvars>") -> str:
    """Return the file text with the drafted rule added at the end of its collection."""
    kind = rule_type(draft)
    collection = collection_name(spoke, kind)
    if draft.get("collection", collection) != collection:
        raise DraftError(f"draft names collection {draft['collection']!r}; a {kind} rule in {spoke} goes in {collection}")
    fields = rule_fields(draft)
    key = f"{index}-{fields['name']}"
    before = parse_rules(text, spoke, path)
    existing = {r["name"] for c in before["collections"] if c["name"] == collection for r in c["rules"]}
    if fields["name"] in existing:
        raise DraftError(f"{path}: {collection} already has a rule named {fields['name']}")

    lines = text.splitlines(keepends=True)
    close = _rules_close(lines, collection, path)
    new_text = "".join(lines[:close]) + render_entry(key, fields) + "".join(lines[close:])
    _check_read_back(before, parse_rules(new_text, spoke, path), collection, key, fields, path)
    return new_text


def _check_read_back(before: dict, after: dict, collection: str, key: str, fields: dict, path: str) -> None:
    """Confirm the new rule is in the file with its fields and nothing else changed."""
    added = [r for c in after["collections"] if c["name"] == collection for r in c["rules"] if r["key"] == key]
    if [{k: v for k, v in r.items() if k != "key"} for r in added] != [fields]:
        raise DraftError(f"{path}: read-back of {key} does not match the draft")
    for c in after["collections"]:
        if c["name"] == collection:
            c["rules"] = [r for r in c["rules"] if r["key"] != key]
    if after != before:
        raise DraftError(f"{path}: the insert changed something other than {key}")


def write_rule(repo: Path, env_site: str, spoke: str, draft: dict) -> tuple[Path, str]:
    """Add the draft to one env-site's spoke file on disk; return the path and the new key."""
    hubs = load_hubs(LocalSource(repo))
    if env_site not in hubs:
        raise DraftError(f"unknown env-site {env_site!r}")
    if spoke not in hubs[env_site].spokes:
        raise DraftError(f"spoke {spoke!r} is not routed through {env_site}")
    rel = RULES_FILE.format(env_site=env_site, name=spoke)
    path = Path(repo) / rel
    text = path.read_text()
    index = next_index(text, spoke, rule_type(draft), rel)
    path.write_text(insert_rule(text, spoke, draft, index, rel))
    return path, f"{index}-{draft['name']}"
