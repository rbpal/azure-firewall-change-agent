"""Reads the synthetic estate (address plan, routing) that the tools answer from.

Where the files come from is a Source. Tests use LocalSource on the repo
checkout. The deployed app will read main on GitHub; that source is added
when its access method is decided. Every answer carries the source's commit,
so a reader can tell which version of the estate it came from.
"""

import ipaddress
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

ADDRESS_PLAN = "data/estate/address-plan.yaml"
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


class EstateError(Exception):
    """The estate data itself is malformed. Never caused by the caller."""


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
        raise EstateError("address plan has no ranges")
    ranges, seen = [], set()
    for row in rows:
        try:
            net = ipaddress.IPv4Network(row["cidr"])
            kind = row["kind"]
            if kind not in KINDS:
                raise EstateError(f"unknown kind {kind!r} for {net}")
            hosts = tuple(sorted((name, tuple(addrs)) for name, addrs in (row.get("hosts") or {}).items()))
            r = Range(network=net, kind=kind, environment=row["environment"], site=row["site"],
                      region=row["region"], spoke=row.get("spoke"), vnet=row.get("vnet"),
                      ip_group=row.get("ip_group"), holds=row.get("holds"), hosts=hosts)
        except (KeyError, ValueError, TypeError) as exc:
            raise EstateError(f"bad address plan row {row!r}: {exc}") from exc
        if net in seen:
            raise EstateError(f"duplicate range {net}")
        seen.add(net)
        ranges.append(r)
    return ranges
