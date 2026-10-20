"""Reads the synthetic network (address plan, routing) that the tools answer from.

Where the files come from is a Source. Tests use LocalSource on the repo
checkout. The deployed app will read the copy of main in Blob storage that a
GitHub Actions job writes on every push (ADR 0003). Every answer carries the
source's commit, so a reader can tell which version of the network it came from.
"""

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

ADDRESS_PLAN = "data/network/address-plan.yaml"
ROUTING = "data/network/routing.yaml"
KINDS = {"env-site", "shared", "spoke"}


class Source(Protocol):
    def read(self, path: str) -> str: ...

    @property
    def commit(self) -> str | None: ...


class LocalSource:
    """Reads files from a local folder. For tests; commit is unknown."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def read(self, path: str) -> str:
        return (self.root / path).read_text()

    @property
    def commit(self) -> str | None:
        return None


class NetworkDataError(Exception):
    """The network data itself is malformed. Never caused by the caller."""


@dataclass(frozen=True)
class Range:
    network: ipaddress.IPv4Network
    kind: str
    environment: str
    site: str
    region: str
    spoke: str | None = None
    vnet: str | None = None
    ip_group: str | None = None
    holds: str | None = None
    hosts: tuple[tuple[str, tuple[str, ...]], ...] = ()

    @property
    def env_site(self) -> str:
        return f"{self.environment}-{self.region}"


def load_ranges(source: Source) -> list[Range]:
    data = yaml.safe_load(source.read(ADDRESS_PLAN))
    rows = data.get("ranges") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise NetworkDataError("address plan has no ranges")
    ranges, seen = [], set()
    for row in rows:
        try:
            net = ipaddress.IPv4Network(row["cidr"])
            kind = row["kind"]
            if kind not in KINDS:
                raise NetworkDataError(f"unknown kind {kind!r} for {net}")
            hosts = tuple(sorted((name, tuple(addrs)) for name, addrs in (row.get("hosts") or {}).items()))
            r = Range(network=net, kind=kind, environment=row["environment"], site=row["site"],
                      region=row["region"], spoke=row.get("spoke"), vnet=row.get("vnet"),
                      ip_group=row.get("ip_group"), holds=row.get("holds"), hosts=hosts)
        except (KeyError, ValueError, TypeError) as exc:
            raise NetworkDataError(f"bad address plan row {row!r}: {exc}") from exc
        if net in seen:
            raise NetworkDataError(f"duplicate range {net}")
        seen.add(net)
        ranges.append(r)
    return ranges


@dataclass(frozen=True)
class OnPremRange:
    """One on-prem user subnet: which data centre it is at, and how that site reaches Azure."""

    network: ipaddress.IPv4Network
    kind: str
    location: str
    holds: str | None = None
    ip_group: str | None = None
    connection: str | None = None


def load_onprem(source: Source) -> list[OnPremRange]:
    """Read the on-prem user subnets from the address plan, with each site's connection from routing."""
    plan = yaml.safe_load(source.read(ADDRESS_PLAN))
    links = (yaml.safe_load(source.read(ROUTING)) or {}).get("onprem") or {}
    rows = (plan.get("onprem") if isinstance(plan, dict) else None) or []
    out, seen = [], set()
    for row in rows:
        try:
            net = ipaddress.IPv4Network(row["cidr"])
            location = row["location"]
            if location not in links:
                raise NetworkDataError(f"on-prem site {location!r} for {net} has no connection in routing")
            if not row["kind"].startswith("users-"):
                raise NetworkDataError(f"unknown on-prem kind {row['kind']!r} for {net}")
            r = OnPremRange(network=net, kind=row["kind"], location=location, holds=row.get("holds"),
                            ip_group=row.get("ip_group"), connection=links[location].get("connection"))
        except (KeyError, ValueError, TypeError) as exc:
            raise NetworkDataError(f"bad on-prem row {row!r}: {exc}") from exc
        if net in seen:
            raise NetworkDataError(f"duplicate on-prem range {net}")
        seen.add(net)
        out.append(r)
    return out


@dataclass(frozen=True)
class Hub:
    """One env-site's secured hub: its firewall, its policy and the spokes routed through it."""

    firewall: str
    firewall_policy: str
    spokes: frozenset[str] = frozenset()
    public_ip: str | None = None


def load_hubs(source: Source) -> dict[str, Hub]:
    """Read routing.yaml: each env-site has exactly one hub firewall and policy."""
    data = yaml.safe_load(source.read(ROUTING))
    sites = data.get("env_sites") if isinstance(data, dict) else None
    if not isinstance(sites, dict) or not sites:
        raise NetworkDataError("routing has no env_sites")
    hubs = {}
    for env_site, site in sites.items():
        try:
            hubs[env_site] = Hub(firewall=site["firewall"], firewall_policy=site["firewall_policy"],
                                 spokes=frozenset(site.get("spokes") or {}), public_ip=site.get("public_ip"))
        except (KeyError, TypeError) as exc:
            raise NetworkDataError(f"routing entry {env_site!r} has no firewall or policy: {exc}") from exc
    return hubs
