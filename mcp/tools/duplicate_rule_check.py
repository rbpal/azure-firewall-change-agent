"""duplicate_rule_check: does an existing rule already allow this new rule's traffic?

The agent sends the rule it plans to add and the env-site, such as dev-eastus2.
The tool reads every rules file of that env-site from main, the hub file included.
It lists each existing rule that already allows all of the new rule's traffic.

"duplicate" means the existing rule allows exactly the same traffic.
"covers" means it allows the same traffic and more, such as a wider range.
An empty list means no existing rule allows it, so the new rule is needed.
A remove request uses the same answer: only a "duplicate" may be deleted.

IP groups are swapped for their addresses before comparing.
A network rule can cover an application rule, because Azure checks network rules first.
The maths is done here, in code, so the same input always gives the same answer.
Each answer includes the commit it read.
"""

import ipaddress

from errors import BadArguments
from tools.read_addressplan_routing import Source, load_hubs
from tools.read_env_site_ipgroup import IP_GROUPS_FILE, read_env_site, read_ip_groups

TYPES = {"network", "application", "dnat"}
ALLOWED_KEYS = {
    "network": {"protocols", "source_addresses", "source_ip_groups", "destination_addresses",
                "destination_ip_groups", "destination_fqdns", "destination_ports"},
    "application": {"protocols", "source_addresses", "source_ip_groups", "destination_fqdns"},
    "dnat": {"protocols", "source_addresses", "source_ip_groups", "destination_address",
             "destination_ports", "translated_address", "translated_port"},
}
ANY = "*"
ALL_PORTS = (1, 65535)
EVERYWHERE = ipaddress.IPv4Network("0.0.0.0/0")


def _strings(rule: dict, key: str) -> list[str]:
    """Return a list field of a rule, or an empty list. Refuse anything that is not a list of strings."""
    value = rule.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
        raise BadArguments(f"{key} must be a list of non-empty strings")
    return [v.strip() for v in value]


def _networks(cidrs: list[str], key: str) -> list[ipaddress.IPv4Network]:
    """Turn address strings into networks. "*" means every address."""
    out = []
    for c in cidrs:
        if c == ANY:
            out.append(EVERYWHERE)
            continue
        try:
            out.append(ipaddress.IPv4Network(c, strict=True))
        except ValueError as exc:
            raise BadArguments(f"{key}: {c!r} is not an IPv4 address or CIDR") from exc
    return out


def _addresses(rule: dict, side: str, groups: dict[str, list[str]]) -> list[ipaddress.IPv4Network]:
    """Collect one side's addresses, with each IP group swapped for its CIDRs."""
    cidrs = _strings(rule, f"{side}_addresses")
    for name in _strings(rule, f"{side}_ip_groups"):
        if name not in groups:
            raise BadArguments(f"IP group {name!r} does not exist in this env-site")
        cidrs += groups[name]
    return _networks(cidrs, f"{side}_addresses")


def _within(inner: list[ipaddress.IPv4Network], outer: list[ipaddress.IPv4Network]) -> bool:
    """True when every inner network sits inside the outer networks taken together."""
    merged = list(ipaddress.collapse_addresses(outer))
    return all(any(n.subnet_of(m) for m in merged) for n in ipaddress.collapse_addresses(inner))


def _ports(values: list[str]) -> list[tuple[int, int]]:
    """Turn port strings such as "443", "440-450" or "*" into ranges."""
    out = []
    for v in values:
        if v == ANY:
            out.append(ALL_PORTS)
            continue
        low, _, high = v.partition("-")
        if not low.isdigit() or (high and not high.isdigit()):
            raise BadArguments(f"{v!r} is not a port, a port range or *")
        lo, hi = int(low), int(high or low)
        if not 1 <= lo <= hi <= 65535:
            raise BadArguments(f"{v!r} is outside 1-65535")
        out.append((lo, hi))
    return out


def _ports_within(inner: list[tuple[int, int]], outer: list[tuple[int, int]]) -> bool:
    """True when every inner port range sits inside the outer ranges taken together."""
    merged = []
    for lo, hi in sorted(outer):
        if merged and lo <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], hi))
        else:
            merged.append((lo, hi))
    return all(any(m[0] <= lo and hi <= m[1] for m in merged) for lo, hi in inner)


def _fqdn_within(name: str, patterns: list[str]) -> bool:
    """True when a pattern matches the name: the same name, "*", or "*.domain" for a name under that domain."""
    name = name.lower()
    for p in (p.lower() for p in patterns):
        if p in (ANY, name):
            return True
        if p.startswith("*.") and name.endswith(p[1:]):
            return True
    return False


def _protocols_within(inner: list[str], outer: list[str]) -> bool:
    """True when every inner protocol is in the outer list. "Any" covers all."""
    outer_set = {p.lower() for p in outer}
    return "any" in outer_set or all(p.lower() in outer_set for p in inner)


def _app_ports(protocols: list[str]) -> list[tuple[int, int]]:
    """Read the ports out of application protocols such as "Https:443"."""
    ports = []
    for p in protocols:
        _, _, port = p.partition(":")
        ports += _ports([port]) if port else []
    return ports


def _covers(existing: dict, kind: str, new: dict, new_type: str, groups: dict[str, list[str]]) -> bool:
    """True when the existing rule allows all of the new rule's traffic."""
    if not _within(_addresses(new, "source", groups), _addresses(existing, "source", groups)):
        return False
    if new_type == "network" and kind == "network":
        return (_protocols_within(new["protocols"], existing.get("protocols", []))
                and _ports_within(_ports(new["destination_ports"]), _ports(existing.get("destination_ports", [])))
                and _destination_within(new, existing, groups))
    if new_type == "application" and kind == "application":
        return (_protocols_within(new["protocols"], existing.get("protocols", []))
                and all(_fqdn_within(f, existing.get("destination_fqdns", [])) for f in new["destination_fqdns"]))
    if new_type == "application" and kind == "network":
        # A network rule that allows the TCP port to any address, or to the same names, matches first.
        to_all = EVERYWHERE in _addresses(existing, "destination", groups)
        to_names = all(_fqdn_within(f, existing.get("destination_fqdns", [])) for f in new["destination_fqdns"])
        return (_protocols_within(["TCP"], existing.get("protocols", []))
                and _ports_within(_app_ports(new["protocols"]), _ports(existing.get("destination_ports", [])))
                and (to_all or to_names))
    if new_type == "dnat" and kind == "dnat":
        return (_protocols_within(new["protocols"], existing.get("protocols", []))
                and new["destination_address"] == existing.get("destination_address")
                and _ports_within(_ports(new["destination_ports"]), _ports(existing.get("destination_ports", [])))
                and new["translated_address"] == existing.get("translated_address")
                and new["translated_port"] == existing.get("translated_port"))
    return False


def _destination_within(new: dict, existing: dict, groups: dict[str, list[str]]) -> bool:
    """True when the existing network rule allows every destination of the new one."""
    new_names = new.get("destination_fqdns", [])
    if new_names and not all(_fqdn_within(f, existing.get("destination_fqdns", [])) for f in new_names):
        return False
    new_nets = _addresses(new, "destination", groups)
    return not new_nets or _within(new_nets, _addresses(existing, "destination", groups))


def _check_new_rule(new_type, rule) -> dict:
    """Check the new rule's fields for its type and return a clean copy."""
    if new_type not in TYPES:
        raise BadArguments(f"type must be one of {sorted(TYPES)}")
    if not isinstance(rule, dict) or not rule:
        raise BadArguments("rule must be an object with the new rule's fields")
    extra = set(rule) - ALLOWED_KEYS[new_type]
    if extra:
        raise BadArguments(f"fields not used by a {new_type} rule: {sorted(extra)}")
    clean = {}
    for key in rule:
        if key in ("destination_address", "translated_address", "translated_port"):
            if not isinstance(rule[key], str) or not rule[key].strip():
                raise BadArguments(f"{key} must be a non-empty string")
            clean[key] = rule[key].strip()
        else:
            clean[key] = _strings(rule, key)
    if not clean.get("protocols"):
        raise BadArguments("protocols is required")
    if not (clean.get("source_addresses") or clean.get("source_ip_groups")):
        raise BadArguments("a source is required: source_addresses or source_ip_groups")
    needed = {"network": ["destination_ports"], "application": ["destination_fqdns"],
              "dnat": ["destination_address", "destination_ports", "translated_address", "translated_port"]}
    for key in needed[new_type]:
        if not clean.get(key):
            raise BadArguments(f"{key} is required for a {new_type} rule")
    if new_type == "network" and not any(clean.get(k) for k in
                                         ("destination_addresses", "destination_ip_groups", "destination_fqdns")):
        raise BadArguments("a destination is required for a network rule")
    return clean


def duplicate_rule_check(caller, arguments: dict, source: Source) -> dict:
    """Check the arguments, compare the new rule with every existing rule and list the ones that allow it."""
    if not isinstance(arguments, dict) or set(arguments) - {"env_site", "type", "rule"}:
        raise BadArguments("only three arguments are accepted: env_site, type and rule")
    env_site, hubs = arguments.get("env_site"), load_hubs(source)
    if not isinstance(env_site, str) or env_site not in hubs:
        raise BadArguments(f"env_site must be one of {sorted(hubs)}")
    new_type = arguments.get("type")
    new = _check_new_rule(new_type, arguments.get("rule"))
    groups = read_ip_groups(source, env_site)
    _addresses(new, "source", groups)
    _addresses(new, "destination", groups)
    _ports(new.get("destination_ports", []))
    if new_type == "application":
        _app_ports(new["protocols"])
    groups_read = read_env_site(source, env_site)
    matches = []
    for group in groups_read:
        for c in group["collections"]:
            if c["action"] not in ("Allow", "Dnat"):
                continue
            for existing in c["rules"]:
                if not _covers(existing, c["type"], new, new_type, groups):
                    continue
                # Exact when each rule allows all of the other's traffic.
                exact = c["type"] == new_type and _covers(new, new_type, existing, c["type"], groups)
                matches.append({"relation": "duplicate" if exact else "covers", "key": existing["key"],
                                "type": c["type"], "collection": c["name"], "file": group["file"],
                                "rule": {k: v for k, v in existing.items() if k != "key"}})
    return {"env_site": env_site, "already_allowed": bool(matches), "matches": matches,
            "source": {"files": [g["file"] for g in groups_read] + [IP_GROUPS_FILE.format(env_site=env_site)],
                       "commit": source.commit}}

