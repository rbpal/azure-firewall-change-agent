"""dnat_port_check: is this TCP port already published on this env-site's firewall public IP?

Example: env_site "prod-eastus2", protocols ["TCP"], destination_ports ["2221"]
answers conflicts_found and names rule 001-sftp-woodgrove-to-xferSftp in xfer.tfvars,
which already publishes TCP 2221 on 192.0.2.10.

Why the agent uses it: RB-02-3 and STD-COLL-06 say a public port is used once per
firewall public IP and protocol, and a DNAT draft must escalate with
port_already_published when it is taken. duplicate_rule_check only lists rules that
allow the same flow, so it cannot answer this. On 2026-10-28 the agent stopped
RITM0011020 because nothing could. Tier 1 imports the same comparison, so the agent
and CI cannot disagree.

How it decides: it reads every DNAT rule in every rules file of the env-site's
policy, the hub file included, at the pinned commit. An existing rule conflicts when
its destination IP overlaps this firewall's public IP from routing.yaml, it shares a
protocol with the request, and its port ranges overlap the requested ports. The
source does not matter. A UDP rule on the same port does not conflict with TCP.

Safety rule: it never says a port is free unless it read everything. A rules file it
cannot read, or a DNAT rule whose protocols, destination or ports it cannot parse, is
returned as inconclusive, so the agent asks the engineer. Workflow policy drafts new
inbound DNAT for TCP only, so a request for any other protocol is refused. It reads
only; it never changes a rule.
"""

import ipaddress

from data_readers.read_addressplan_routing import NetworkDataError, Source, load_hubs
from data_readers.read_env_site_ipgroup import HUB, RULES_FILE, parse_rules
from errors import BadArguments

ARGUMENTS = {"env_site", "protocols", "destination_ports"}
DNAT_PROTOCOLS = {"TCP", "UDP"}
REQUEST_PROTOCOLS = {"TCP"}  # workflow policy (2026-10-28), not an Azure limit: new inbound DNAT is TCP only
NAT_PORTS = (1, 63999)  # Azure Firewall known issues: NAT rules support ports 1-63999 only
COVERAGE = ("Read every DNAT rule in the {files} rules files of {policy} (the hub file and each spoke "
            "in routing.yaml) at commit {commit}. A rule added outside the pipeline is not in main, "
            "so it is not seen here.")


def _port_ranges(values, limit: tuple[int, int] = (1, 65535)) -> list[tuple[int, int]]:
    """Turn port strings such as "22" or "2220-2224" into ranges; raise ValueError on anything else."""
    if not isinstance(values, list) or not values:
        raise ValueError("no ports")
    out = []
    for v in values:
        low, _, high = str(v).strip().partition("-")
        if not low.isdigit() or (high and not high.isdigit()):
            raise ValueError(f"{v!r} is not a port or a port range")
        lo, hi = int(low), int(high or low)
        if not limit[0] <= lo <= hi <= limit[1]:
            raise ValueError(f"{v!r} is outside {limit[0]}-{limit[1]}")
        out.append((lo, hi))
    return out


def published(rule: dict) -> tuple[set[str], list, list[tuple[int, int]]]:
    """A DNAT rule's protocols, destination networks and port ranges; raise ValueError when any cannot be read."""
    protocols = {str(p).strip().upper() for p in rule.get("protocols") or []}
    if not protocols or not protocols <= DNAT_PROTOCOLS:
        raise ValueError(f"its protocols {sorted(protocols)} are not TCP or UDP")
    value = rule.get("destination_address", rule.get("destination_addresses"))
    addresses = [value] if isinstance(value, str) else list(value or [])
    if not addresses:
        raise ValueError("it has no destination address")
    try:
        networks = [ipaddress.ip_network("0.0.0.0/0" if str(a).strip() == "*" else str(a).strip(), strict=False)
                    for a in addresses]
    except ValueError as exc:
        raise ValueError(f"its destination {addresses} cannot be read: {exc}") from exc
    try:
        ports = _port_ranges(rule.get("destination_ports"))
    except ValueError as exc:
        raise ValueError(f"its destination_ports cannot be read: {exc}") from exc
    return protocols, networks, ports


def overlap(a: tuple, b: tuple) -> list[str]:
    """The ports two parsed DNAT rules both publish on an overlapping destination IP under a shared protocol."""
    (pa, na, ra), (pb, nb, rb) = a, b
    if not pa & pb or not any(x.overlaps(y) for x in na for y in nb):
        return []
    shared = sorted({(max(x[0], y[0]), min(x[1], y[1])) for x in ra for y in rb if max(x[0], y[0]) <= min(x[1], y[1])})
    return [str(lo) if lo == hi else f"{lo}-{hi}" for lo, hi in shared]


def _request(arguments: dict, public_ip: str) -> tuple:
    """The requested publication, parsed; refuse a protocol the policy does not draft or a port DNAT cannot use."""
    protocols = arguments.get("protocols")
    if not isinstance(protocols, list) or not protocols or not all(isinstance(v, str) for v in protocols):
        raise BadArguments('protocols must be a non-empty list such as ["TCP"]')
    found = {v.strip().upper() for v in protocols}
    if not found <= REQUEST_PROTOCOLS:
        raise BadArguments(f"workflow policy drafts new inbound DNAT for TCP only, not {sorted(found - REQUEST_PROTOCOLS)}; "
                           "such a ticket goes back to the engineer")
    try:
        ports = _port_ranges(arguments.get("destination_ports"), NAT_PORTS)
    except ValueError as exc:
        raise BadArguments(f"destination_ports must be a list such as [\"22\"]; a DNAT port is 1-63999: {exc}") from exc
    return found, [ipaddress.ip_network(public_ip)], ports


def dnat_port_check(caller, arguments: dict, source: Source) -> dict:
    """Check the arguments, read every DNAT rule of the env-site's policy and list rules that already publish the port."""
    if not isinstance(arguments, dict) or set(arguments) - ARGUMENTS:
        raise BadArguments("only three arguments are accepted: env_site, protocols and destination_ports")
    env_site, hubs = arguments.get("env_site"), load_hubs(source)
    if not isinstance(env_site, str) or env_site not in hubs:
        raise BadArguments(f"env_site must be one of {sorted(hubs)}")
    hub = hubs[env_site]
    if not hub.public_ip:
        raise NetworkDataError(f"routing.yaml has no public_ip for {env_site}")
    request = _request(arguments, hub.public_ip)
    conflicts, inconclusive, files, rules_read = [], [], [], 0
    for name in sorted(hub.spokes) + [HUB]:
        path = RULES_FILE.format(env_site=env_site, name=name)
        files.append(path)
        try:
            group = parse_rules(source.read(path), name, path)
        except (NetworkDataError, OSError) as exc:
            inconclusive.append({"code": "rules_file_unreadable", "file": path, "detail": str(exc)})
            continue
        for c in group["collections"]:
            if c["type"] != "dnat":
                continue
            for rule in c["rules"]:
                rules_read += 1
                where = {"key": rule["key"], "file": path, "rule_collection_group": group["rule_collection_group"],
                         "collection": c["name"]}
                try:
                    shared = overlap(request, published(rule))
                except ValueError as exc:
                    inconclusive.append({"code": "rule_unreadable", **where, "detail": str(exc)})
                    continue
                if shared:
                    conflicts.append({**where, "protocols": rule.get("protocols"),
                                      "destination_address": rule.get("destination_address"),
                                      "destination_ports": rule.get("destination_ports"), "overlapping_ports": shared,
                                      "source_addresses": rule.get("source_addresses", []),
                                      "source_ip_groups": rule.get("source_ip_groups", []),
                                      "translated_address": rule.get("translated_address"),
                                      "translated_port": rule.get("translated_port")})
    status = "conflicts_found" if conflicts else "inconclusive" if inconclusive else "no_conflicts"
    return {"env_site": env_site, "firewall": hub.firewall, "firewall_policy": hub.firewall_policy,
            "firewall_public_ip": hub.public_ip,
            "requested": {"protocols": sorted(request[0]), "destination_ports": arguments["destination_ports"]},
            "status": status, "conflicts": conflicts, "inconclusive": inconclusive,
            "coverage": COVERAGE.format(files=len(files), policy=hub.firewall_policy, commit=source.commit or "unknown"),
            "dnat_rules_read": rules_read, "source": {"files": files, "commit": source.commit}}
