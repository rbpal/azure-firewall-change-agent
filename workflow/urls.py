"""URL destinations: what a pasted URL approves, and when it disagrees with the ticket's protocol or port.

Example: a destination `https://api.litware.example/v1/upload` on an HTTPS 443 ticket approves
the hostname api.litware.example on port 443; the rule allows every path on that host, and the
URL stays on the ticket. `https://api.litware.example:8443/v1/upload` on the same ticket is a
conflict: the URL says 8443, the ticket says 443. The same URL on a TCP ticket is non-HTTP traffic
to a hostname.

Why: a firewall application rule matches a hostname and a port, never a path (schema.json
`address` description, STD-COLL-03). Code takes the hostname exactly as the URL writes it and
returns any port conflict to the engineer, so neither the agent nor the workflow picks a value.

Safety rule: the hostname is never corrected or replaced, and a conflict is never resolved here.
On an HTTP or HTTPS ticket the URL's scheme (the schema allows http and https) must be the protocol,
and a port the URL states must be the ticket's one port: else url_port_conflict. On a TCP, UDP, ICMP
or Any ticket a URL is non-HTTP traffic to a hostname: non_http_to_hostname (RB-01-6).
"""

from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit

CODE = "url_port_conflict"
NON_HTTP = "non_http_to_hostname"
WEB = {"HTTP", "HTTPS"}  # the protocols a URL can carry; the schema allows http:// and https:// only


def url_host(url: str) -> str | None:
    """The hostname a URL names, as the URL writes it apart from case; None when it names none."""
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


def url_port(url: str) -> int | None:
    """The port a URL states explicitly, such as 8443 in https://host:8443/; None when it states none."""
    try:
        return urlsplit(url).port
    except ValueError:
        return None


INVALID_URL, INVALID_HOSTNAME = "invalid_url", "invalid_hostname"
_LABEL = re.compile(r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?")
_PORT = re.compile(r"[0-9]{1,5}")


def _character_problems(value: str) -> list[str]:
    """Spaces, tabs, line breaks, invisible characters and non-ASCII letters, each with its position."""
    out = []
    for i, ch in enumerate(value, 1):
        if ch == " ":
            out.append(f"a space at character {i}")
        elif ch == "\t":
            out.append(f"a tab at character {i}")
        elif ch in "\n\r":
            out.append(f"a line break at character {i}")
        elif unicodedata.category(ch)[0] in "ZC":
            out.append(f"an invisible character U+{ord(ch):04X} at character {i}")
        elif not ch.isascii():
            out.append(f"a non-ASCII character {ch!r} (U+{ord(ch):04X}) at character {i}, which can look like an "
                       "ASCII letter")
    return out


def _host_problems(host: str, wildcard: bool) -> list[str]:
    """What is wrong with one hostname's dots, labels and characters; the host is lower-cased first."""
    if not host:
        return ["it has no hostname"]
    if wildcard and host == "*":  # allowed by the schema; a caution for the engineer (STD-COLL-02, RB-01-7)
        return []
    out, labels = [], host.lower().split(".")
    if wildcard and labels[0] == "*":
        labels = labels[1:] or ["*"]
    if host.startswith("."):
        out.append("it starts with a dot")
    if host.endswith("."):
        out.append("it ends with a dot")
    if ".." in host:
        out.append("it has two dots in a row")
    if len(labels) < 2 and labels != ["*"]:
        out.append("it has no domain; a hostname needs at least one dot")
    for label in [x for x in labels if x]:
        bad = sorted({c for c in label if not (c.isascii() and (c.isalnum() or c == "-"))})
        if bad:
            out.append(f"the character{'s' if len(bad) > 1 else ''} {', '.join(repr(c) for c in bad)} "
                       f"{'are' if len(bad) > 1 else 'is'} not allowed in a hostname ({label!r})")
        elif label.startswith("-") or label.endswith("-"):
            out.append(f"the label {label!r} starts or ends with a hyphen")
        elif len(label) > 63:
            out.append(f"the label {label[:12]!r}... is {len(label)} characters; a label holds at most 63")
        elif not _LABEL.fullmatch(label):
            out.append(f"the label {label!r} is not valid")
    last = labels[-1] if labels else ""
    if len(labels) >= 2 and last and not re.fullmatch(r"[a-z]{2,63}", last):
        out.append(f"the last label {last!r} must be 2 to 63 letters")
    return out


def url_problems(url) -> list[str]:
    """Why a ticket URL cannot be used as written; empty when it can. Never changes the URL."""
    if not isinstance(url, str):
        return ["it is not text"]
    out = _character_problems(url)
    scheme, sep, rest = url.partition("://")
    if not sep:
        return out + ["it has no scheme; a URL starts with https:// or http://"]
    if scheme.lower() not in ("http", "https"):
        out.append(f"the scheme is {scheme!r}; only http and https are allowed")
    netloc = re.split(r"[/?#]", rest, maxsplit=1)[0]
    if "@" in netloc:
        out.append("it holds a user name or password before the hostname (@)")
        netloc = netloc.rsplit("@", 1)[1]
    host, colon, port = netloc.partition(":")
    if colon and not (_PORT.fullmatch(port) and 1 <= int(port) <= 65535):
        out.append(f"the port {port!r} is not a number from 1 to 65535")
    out += _host_problems(host.strip(), wildcard=False) if not _character_problems(host) else []
    return out


def hostname_problems(name) -> list[str]:
    """Why a ticket hostname cannot be used as written; empty when it can. Never changes the name."""
    if not isinstance(name, str):
        return ["it is not text"]
    out = _character_problems(name)
    if "://" in name or "/" in name:
        return out + ["it looks like a URL; give it as a url, or give only the hostname"]
    if name != name.lower():
        out.append("it has upper-case letters; a hostname on the ticket is written in lower case")
    return out + (_host_problems(name, wildcard=True) if not out else [])


def name_findings(ticket) -> list[dict]:
    """Every URL or hostname on the ticket that cannot be used as written: where, code and a plain message."""
    out = []
    for side in ("sources", "destination"):
        entries = ticket.get(side) if isinstance(ticket, dict) else None
        for i, entry in enumerate(entries if isinstance(entries, list) else []):
            if not isinstance(entry, dict):
                continue
            for key, check, code, what in (("url", url_problems, INVALID_URL, "URL"),
                                           ("fqdn", hostname_problems, INVALID_HOSTNAME, "hostname")):
                if key in entry and (problems := check(entry[key])):
                    out.append({"where": f"{side}/{i}/{key}", "code": code,
                                "message": f"{entry[key]!r} is not a valid {what}: " + "; ".join(problems)
                                           + ". The workflow will not correct it; edit the ticket with the intended "
                                           "value."})
    return out


def url_conflicts(ticket) -> list[dict]:
    """Every URL destination that disagrees with the ticket's protocol or ports, each with its code."""
    if not isinstance(ticket, dict) or not isinstance(ticket.get("destination"), list):
        return []
    protocol, ports = str(ticket.get("protocol", "")), [str(p) for p in ticket.get("ports") or []]
    out = []
    for i, entry in enumerate(ticket["destination"]):
        url = entry.get("url") if isinstance(entry, dict) else None
        if not isinstance(url, str) or url_problems(url):  # a malformed URL is reported once, by name_findings
            continue
        scheme, port = urlsplit(url).scheme.upper(), url_port(url)
        if protocol.upper() not in WEB:
            out.append({"where": f"destination/{i}/url", "url": url, "port": port, "code": NON_HTTP,
                        "message": f"{url}: a URL is {scheme} traffic to a hostname, but the ticket's protocol is "
                                   f"{protocol or 'missing'}. Non-HTTP traffic to a hostname would pin addresses that "
                                   "can change (RB-01-6); edit the ticket so its protocol and destination agree."})
            continue
        problems = []
        if protocol.upper() != scheme:
            problems.append(f"its scheme is {scheme} but the ticket's protocol is {protocol or 'missing'}")
        if port is not None and ports != [str(port)]:
            problems.append(f"it states port {port} but the ticket's ports are {', '.join(ports) or 'missing'}")
        if problems:
            out.append({"where": f"destination/{i}/url", "url": url, "port": port, "code": CODE,
                        "message": f"{url}: " + " and ".join(problems) + ". The rule takes one protocol and port, "
                                   "and the workflow will not pick them; edit the ticket so the URL, protocol and ports "
                                   "agree."})
    return out
