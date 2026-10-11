"""dns_lookup_for_fqdn: is the URL valid, and does its hostname resolve to an IP?

Example: "https://www.google.com/search?q=x" -> host www.google.com, port 443,
resolves true, its CNAME chain, A and AAAA records, TTL and DNS status. A URL
that is not valid is refused with the reason.

The agent uses it to put real DNS answers in the PR's DNS section, so the
engineer sees what an FQDN rule will match. The model never states an IP for
a hostname; this tool does.

Safety rule: it only asks DNS. It never fetches the URL, so a crafted URL
cannot make the tool reach an internal service (server-side request forgery).
"""

import ipaddress
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import urlsplit

import dns.exception
import dns.message
import dns.rdatatype
import dns.resolver

from errors import BadArguments

# Azure DNS. It answers only from inside a VNet; the Function app reaches it
# through VNet integration. The Basic firewall has no DNS proxy and uses the
# same resolver, so the tool sees the answer the firewall will.
AZURE_DNS = "168.63.129.16"
DEFAULT_PORTS = {"https": 443, "http": 80}
_LABEL = re.compile(r"^(?!-)[a-z0-9-]{1,63}(?<!-)$")


@dataclass
class Reply:
    """One DNS answer for one record type."""
    rcode: str
    cnames: list[str] = field(default_factory=list)
    addresses: list[str] = field(default_factory=list)
    ttl: int | None = None


Lookup = Callable[[str, str], Reply]


def parse_target(text) -> tuple[str, int | None, str | None]:
    """Turn a URL or bare hostname into (host, port, scheme); reject anything else."""
    if not isinstance(text, str) or not text.strip():
        raise BadArguments("target must be a non-empty string")
    text = text.strip()
    if "://" not in text:
        text = "//" + text
    try:
        parts = urlsplit(text)
        port = parts.port
    except ValueError as exc:
        raise BadArguments(f"{text.lstrip('/')!r} is not a URL or hostname") from exc
    scheme = parts.scheme.lower() or None
    if scheme is not None and scheme not in DEFAULT_PORTS:
        raise BadArguments(f"scheme {scheme!r} is not supported; use http, https or a bare hostname")
    if parts.username is not None or parts.password is not None:
        raise BadArguments("the target must not contain a user name or password")
    host = (parts.hostname or "").rstrip(".")
    if port is None and scheme is not None:
        port = DEFAULT_PORTS[scheme]
    return check_hostname(host), port, scheme


def check_hostname(host: str) -> str:
    """Return the hostname in lower case if it is a valid DNS name with a dot; else raise."""
    if not host:
        raise BadArguments("the target has no hostname")
    try:
        ipaddress.ip_address(host)
        raise BadArguments(f"{host} is an IP address; DNS lookup needs a hostname")
    except ValueError:
        pass
    if host.startswith("*"):
        raise BadArguments(f"{host} is a wildcard; look up a concrete hostname under it")
    labels = host.split(".")
    if len(host) > 253 or len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise BadArguments(f"{host!r} is not a valid hostname")
    return host


def dnspython_lookup(nameserver: str, timeout: float = 5.0) -> Lookup:
    """Build a lookup that asks one nameserver, follows CNAMEs and never raises on NXDOMAIN."""
    resolver = dns.resolver.Resolver(configure=False)
    resolver.nameservers = [nameserver]
    resolver.lifetime = timeout

    def lookup(host: str, rdtype: str) -> Reply:
        """Ask for one record type of host and return what came back."""
        try:
            answer = resolver.resolve(host, rdtype, raise_on_no_answer=False)
        except dns.resolver.NXDOMAIN:
            return Reply(rcode="NXDOMAIN")
        chain = answer.response.resolve_chaining()
        cnames = [str(rr.target).rstrip(".") for rrset in chain.cnames for rr in rrset]
        addresses = [rr.address for rr in chain.answer] if chain.answer else []
        ttl = chain.minimum_ttl if chain.answer else None
        return Reply(rcode="NOERROR", cnames=cnames, addresses=addresses, ttl=ttl)

    return lookup


def resolve(host: str, lookup: Lookup) -> dict:
    """Look up A and AAAA for host, merge them, and say whether it resolves to an IP."""
    a = lookup(host, "A")
    if a.rcode == "NXDOMAIN":
        return {"resolves": False, "reason": "the name does not exist in DNS (NXDOMAIN)",
                "rcode": "NXDOMAIN", "cname_chain": [], "a": [], "aaaa": [], "ttl": None}
    aaaa = lookup(host, "AAAA")
    ttls = [t for t in (a.ttl, aaaa.ttl) if t is not None]
    resolves = bool(a.addresses or aaaa.addresses)
    return {
        "resolves": resolves,
        "reason": None if resolves else "the name exists but has no A or AAAA record",
        "rcode": a.rcode,
        "cname_chain": a.cnames or aaaa.cnames,
        "a": sorted(set(a.addresses), key=ipaddress.ip_address),
        "aaaa": sorted(set(aaaa.addresses), key=ipaddress.ip_address),
        "ttl": min(ttls) if ttls else None,
    }


def dns_lookup_for_fqdn(caller, arguments: dict, lookup: Lookup | None = None,
                        resolver_name: str = AZURE_DNS) -> dict:
    """Answer the tool call: parse the target, ask DNS, return the records and where they came from."""
    if not isinstance(arguments, dict) or set(arguments) - {"target"}:
        raise BadArguments("only one argument is accepted: target")
    host, port, scheme = parse_target(arguments.get("target"))
    result = {"input": arguments["target"], "host": host, "port": port, "scheme": scheme}
    result.update(resolve(host, lookup or dnspython_lookup(resolver_name)))
    result["resolver"] = resolver_name
    result["queried_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return result
