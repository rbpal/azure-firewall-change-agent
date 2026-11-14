"""locate_address_for_env_site: which environment, site and workload an address belongs to.

Longest-prefix match on the address plan, the way a router picks a route:
of all ranges that contain the input, the most specific one wins. The model
never states where an address lives; this tool does, from the plan in the
repo.

Each answer also names the hub firewall, its policy and its public IP for the
address's env-site, from routing.yaml. A DNAT rule's destination is that public IP. Code takes the firewalls for a request from the env-sites
of its source and destination; an address outside the plan has none, and the
engineer says where it goes.

An on-prem user subnet (address plan `onprem:`) answers with its data centre
and ExpressRoute connection instead. It has no env-site and no firewall of its
own. Which firewall inspects it is an assumption, carried in the answer as
`inspection` and not verified on a live network (routing.yaml `onprem:`).

Two facts the engineer reviews are named in the answer, never decided here:
`wider_than_plan` when the input spans more than one plan range or holds
addresses no range lists (with those extra blocks and their count), and
`no_owner` when the input sits in an env-site but no spoke or shared range
owns it, as with a planned or unknown subnet. A CIDR with host bits set is
refused with both of its readings; the tool never picks one.

An IP group name, such as ipg-onprem-primary, answers with every plan range
that lists that group and their origin: azure, onprem, or mixed when the plan
lists it on both. The agent looks up each source this way before it picks a
runbook, so the direction comes from the plan, never from a name. A group no
range lists answers origin null: the plan cannot say whether it is an external party's
group or an internal one it does not record, and the tool never guesses.

An address or CIDR no plan range contains also answers `address_space`, from
the three RFC 1918 blocks: rfc1918 when it sits entirely inside one, non_rfc1918
when it overlaps none, mixed when it overlaps one and reaches outside it. This
states only what the number is. non_rfc1918 does not prove a source is on the
internet, and rfc1918 does not prove where a source sits. Python's is_private is
not used: it also answers True for documentation ranges such as 198.51.100.0/24.
"""

import ipaddress
import re

from errors import BadArguments
from data_readers.read_addressplan_routing import (ADDRESS_PLAN, ROUTING, NetworkDataError, Hub, OnPremRange, Range, Source,
                                                   load_hubs, load_onprem, load_ranges)

IP_GROUP = re.compile(r"ipg-[a-z0-9]+(?:-[a-z0-9]+)*")  # STD-NAME-04: lower case, single hyphens
RFC1918 = tuple(ipaddress.IPv4Network(b) for b in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))


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
           "env_site": r.env_site, "firewall": hub.firewall, "firewall_policy": hub.firewall_policy,
           "firewall_public_ip": hub.public_ip}  # a DNAT rule's destination (RB-02-3), from routing.yaml
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
                net = ipaddress.IPv4Network(text, strict=False)
            except ValueError:
                net = None
            if net is not None:
                raise BadArguments(f"{text} has host bits set, so it has two readings: the host "
                                   f"{text.split('/')[0]}/32 or the subnet {net}; the tool will not pick one") from exc
        raise BadArguments(f"{text!r} is not an IPv4 address, a CIDR or an IP group name") from exc


def parse_ip_group(text: str) -> str:
    """Read one IP group name in the STD-NAME-04 shape; refuse anything else, never fix its case or spelling."""
    if not IP_GROUP.fullmatch(text):
        raise BadArguments(f"{text!r} is not an IP group name such as ipg-sett-prod or ipg-onprem-primary: "
                           "lower case letters and digits joined by single hyphens")
    return text


def locate_group(name: str, ranges: list[Range | OnPremRange], hubs: dict[str, Hub]) -> dict:
    """Every plan range that lists this IP group, and whether they sit in Azure, on-prem, or both."""
    members = sorted((r for r in ranges if r.ip_group == name), key=lambda r: r.network)
    origins = {"onprem" if isinstance(r, OnPremRange) else "azure" for r in members}
    result = {"input": name, "matches": [_describe(r, hubs) for r in members],
              "origin": origins.pop() if len(origins) == 1 else "mixed" if origins else None}
    if not members:
        result["reason"] = ("no range in the address plan lists this IP group, so the plan cannot say where it is "
                            "or whether it is an external party's")
    elif result["origin"] == "mixed":
        result["ambiguous"] = "the address plan lists this IP group on both Azure and on-prem ranges"
    return result


def address_space(net: ipaddress.IPv4Network) -> str:
    """Whether a network sits inside RFC 1918 (rfc1918), outside it (non_rfc1918), or across the edge (mixed)."""
    if any(net.subnet_of(block) for block in RFC1918):
        return "rfc1918"
    return "mixed" if any(net.overlaps(block) for block in RFC1918) else "non_rfc1918"


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
        result["address_space"] = address_space(net)
    leaves = [r for r in covered if getattr(r, "kind", "") != "env-site"]
    if leaves:
        extra = [net]
        for r in leaves:
            extra = [piece for block in extra
                     for piece in ([block] if not r.network.overlaps(block) else
                                   [] if block.subnet_of(r.network) else block.address_exclude(r.network))]
        result["wider_than_plan"] = {"plan_ranges": [str(r.network) for r in leaves],
                                     "extra": [str(b) for b in sorted(extra)],
                                     "extra_addresses": sum(b.num_addresses for b in extra)}
    elif containing and getattr(containing[0], "kind", "") == "env-site":
        result["no_owner"] = (f"inside {containing[0].env_site}, but no spoke or shared range in the plan owns it; "
                              "a planned or unknown subnet")
    return result


def locate_address_for_env_site(caller, arguments: dict, source: Source) -> dict:
    """The tool: where one address or IP group lives, in Azure or on-prem, from the plan in the repo."""
    if not isinstance(arguments, dict) or set(arguments) - {"address"}:
        raise BadArguments("only one argument is accepted: address")
    text = arguments.get("address")
    group = isinstance(text, str) and text.strip().lower().startswith("ipg-")
    target = parse_ip_group(text.strip()) if group else parse_address(text)
    hubs = load_hubs(source)
    ranges = load_ranges(source) + load_onprem(source)
    result = locate_group(target, ranges, hubs) if group else locate(target, ranges, hubs)
    result["source"] = {"files": [ADDRESS_PLAN, ROUTING], "commit": source.commit}
    return result
