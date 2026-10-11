"""locate_address_for_env_site: which environment, site and workload an address belongs to.

Longest-prefix match on the address plan, the way a router picks a route:
of all ranges that contain the input, the most specific one wins. The model
never states where an address lives; this tool does, from the plan in the
repo.

Each answer also names the hub firewall and policy of the address's env-site,
from routing.yaml. Code takes the firewalls for a request from the env-sites
of its source and destination; an address outside the plan has none, and the
engineer says where it goes.
"""

import ipaddress

from errors import BadArguments
from data_readers.read_addressplan_routing import ADDRESS_PLAN, ROUTING, NetworkDataError, Hub, Range, Source, load_hubs, load_ranges


def _describe(r: Range, hubs: dict[str, Hub]) -> dict:
    hub = hubs.get(r.env_site)
    if hub is None:
        raise NetworkDataError(f"env-site {r.env_site} is in the address plan but has no hub in routing")
    out = {"cidr": str(r.network), "kind": r.kind, "environment": r.environment, "site": r.site,
           "env_site": r.env_site, "firewall": hub.firewall, "firewall_policy": hub.firewall_policy}
    for key in ("spoke", "vnet", "ip_group", "holds"):
        value = getattr(r, key)
        if value is not None:
            out[key] = value
    return out


def parse_address(text) -> ipaddress.IPv4Network:
    if not isinstance(text, str) or not text.strip():
        raise BadArguments("address must be a non-empty string")
    text = text.strip()
    try:
        return ipaddress.IPv4Network(text, strict=True)
    except ValueError as exc:
        if "/" in text:
            try:
                ipaddress.IPv4Network(text, strict=False)
                raise BadArguments(f"{text} has host bits set; did you mean {ipaddress.IPv4Network(text, strict=False)}?") from exc
            except ValueError:
                pass
        raise BadArguments(f"{text!r} is not an IPv4 address or CIDR") from exc


def locate(net: ipaddress.IPv4Network, ranges: list[Range], hubs: dict[str, Hub]) -> dict:
    containing = sorted((r for r in ranges if net.subnet_of(r.network)), key=lambda r: r.network.prefixlen, reverse=True)
    covered = sorted((r for r in ranges if r.network.subnet_of(net) and r.network != net), key=lambda r: r.network)
    result = {
        "input": str(net) if net.prefixlen < 32 else str(net.network_address),
        "match": _describe(containing[0], hubs) if containing else None,
        "covers": [_describe(r, hubs) for r in covered],
    }
    if containing and net.prefixlen == 32:
        addr = str(net.network_address)
        for name, addrs in containing[0].hosts:
            if addr in addrs:
                result["host"] = name
    if not containing:
        result["reason"] = ("wider than every range in the address plan" if covered
                            else "not in the address plan: not an internal address of this network")
    return result


def locate_address_for_env_site(caller, arguments: dict, source: Source) -> dict:
    if not isinstance(arguments, dict) or set(arguments) - {"address"}:
        raise BadArguments("only one argument is accepted: address")
    net = parse_address(arguments.get("address"))
    result = locate(net, load_ranges(source), load_hubs(source))
    result["source"] = {"files": [ADDRESS_PLAN, ROUTING], "commit": source.commit}
    return result
