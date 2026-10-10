"""locate_address: which environment, site and workload an address belongs to.

Longest-prefix match on the address plan, the way a router picks a route:
of all ranges that contain the input, the most specific one wins. The model
never states where an address lives; this tool does, from the plan in the
repo.
"""

import ipaddress

from errors import BadArguments
from estate import Range, Source, load_ranges


def _describe(r: Range) -> dict:
    out = {"cidr": str(r.network), "kind": r.kind, "environment": r.environment, "site": r.site,
           "region": r.region, "env_site": r.env_site}
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


def locate(net: ipaddress.IPv4Network, ranges: list[Range]) -> dict:
    containing = sorted((r for r in ranges if net.subnet_of(r.network)), key=lambda r: r.network.prefixlen, reverse=True)
    covered = sorted((r for r in ranges if r.network.subnet_of(net) and r.network != net), key=lambda r: r.network)
    result = {
        "input": str(net) if net.prefixlen < 32 else str(net.network_address),
        "found": bool(containing),
        "match": _describe(containing[0]) if containing else None,
        "within": [_describe(r) for r in containing[1:]],
        "covers": [_describe(r) for r in covered],
    }
    if containing and net.prefixlen == 32:
        addr = str(net.network_address)
        for name, addrs in containing[0].hosts:
            if addr in addrs:
                result["host"] = name
    if not containing:
        result["reason"] = ("wider than every range in the address plan" if covered
                            else "not in the address plan: not an internal address of this estate")
    return result


def locate_address(caller, arguments: dict, source: Source) -> dict:
    if not isinstance(arguments, dict) or set(arguments) - {"address"}:
        raise BadArguments("only one argument is accepted: address")
    net = parse_address(arguments.get("address"))
    result = locate(net, load_ranges(source))
    result["source"] = {"file": "data/estate/address-plan.yaml", "commit": source.commit}
    return result
