"""locate_address_for_env_site: which environment, site and workload an address belongs to.

Longest-prefix match on the address plan, the way a router picks a route:
of all ranges that contain the input, the most specific one wins. The model
never states where an address lives; this tool does, from the plan in the
repo.

Each answer also names the hub firewall and policy of the address's env-site,
from routing.yaml. Code takes the firewalls for a request from the env-sites
of its source and destination; an address outside the plan has none, and the
engineer says where it goes.

An on-prem user subnet (address plan `onprem:`) answers with its data centre
and ExpressRoute connection instead. It has no env-site and no firewall of its
own. Which firewall inspects it is an assumption, carried in the answer as
`inspection` and not verified on a live network (routing.yaml `onprem:`).
"""

import ipaddress

from errors import BadArguments
from data_readers.read_addressplan_routing import (ADDRESS_PLAN, ROUTING, NetworkDataError, Hub, OnPremRange, Range, Source,
                                                   load_hubs, load_onprem, load_ranges)


def _describe(r: Range | OnPremRange, hubs: dict[str, Hub]) -> dict:
    """One plan range as the answer shows it, with its firewall, or its on-prem connection."""
    if isinstance(r, OnPremRange):
        out = {"cidr": str(r.network), "kind": r.kind, "location": r.location, "env_site": None, "firewall": None,
               "firewall_policy": None, "connection": r.connection,
               "inspection": "assumed, not verified: only the hub firewall of the Azure end of the flow inspects it"}
        for key in ("ip_group", "holds"):
            if getattr(r, key) is not None:
                out[key] = getattr(r, key)
        return out
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
    """Read one IPv4 address or CIDR; refuse anything else, and CIDRs with host bits set."""
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


def locate(net: ipaddress.IPv4Network, ranges: list[Range | OnPremRange], hubs: dict[str, Hub]) -> dict:
    """Longest-prefix match of one address over the plan's ranges, plus the ranges it covers."""
    containing = sorted((r for r in ranges if net.subnet_of(r.network)), key=lambda r: r.network.prefixlen, reverse=True)
    covered = sorted((r for r in ranges if r.network.subnet_of(net) and r.network != net), key=lambda r: r.network)
    result = {
        "input": str(net) if net.prefixlen < 32 else str(net.network_address),
        "match": _describe(containing[0], hubs) if containing else None,
        "covers": [_describe(r, hubs) for r in covered],
    }
    if containing and net.prefixlen == 32 and isinstance(containing[0], Range):
        addr = str(net.network_address)
        for name, addrs in containing[0].hosts:
            if addr in addrs:
                result["host"] = name
    if not containing:
        result["reason"] = ("wider than every range in the address plan" if covered
                            else "not in the address plan (Azure or on-prem)")
    return result


def locate_address_for_env_site(caller, arguments: dict, source: Source) -> dict:
    """The tool: where one address lives, in Azure or on-prem, from the plan in the repo."""
    if not isinstance(arguments, dict) or set(arguments) - {"address"}:
        raise BadArguments("only one argument is accepted: address")
    net = parse_address(arguments.get("address"))
    hubs = load_hubs(source)
    result = locate(net, load_ranges(source) + load_onprem(source), hubs)
    result["source"] = {"files": [ADDRESS_PLAN, ROUTING], "commit": source.commit}
    return result
