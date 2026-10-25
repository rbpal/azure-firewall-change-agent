"""URL destinations: what a pasted URL approves, and when its port disagrees with the ticket.

Example: a destination `https://api.litware.example/v1/upload` on an HTTPS 443 ticket approves
the hostname api.litware.example on port 443; the rule allows every path on that host, and the
URL stays on the ticket. `https://api.litware.example:8443/v1/upload` on the same ticket is a
conflict: the URL says 8443, the ticket says 443.

Why: a firewall application rule matches a hostname and a port, never a path (schema.json
`address` description, STD-COLL-03). Code takes the hostname exactly as the URL writes it and
returns any port conflict to the engineer, so neither the agent nor the workflow picks a value.

Safety rule: the hostname is never corrected or replaced, and a conflict is never resolved here.
The URL's scheme (the schema allows http and https) must be the ticket's protocol, HTTP or HTTPS.
A port is checked only when the URL states one; a URL without one uses the ticket's ports.
"""

from __future__ import annotations

from urllib.parse import urlsplit

CODE = "url_port_conflict"


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


def url_conflicts(ticket) -> list[dict]:
    """Every URL destination whose scheme, or stated port, disagrees with the ticket's protocol and ports."""
    if not isinstance(ticket, dict) or not isinstance(ticket.get("destination"), list):
        return []
    protocol, ports = str(ticket.get("protocol", "")), [str(p) for p in ticket.get("ports") or []]
    out = []
    for i, entry in enumerate(ticket["destination"]):
        url = entry.get("url") if isinstance(entry, dict) else None
        if not isinstance(url, str):
            continue
        scheme, port = urlsplit(url).scheme.upper(), url_port(url)
        problems = []
        if protocol.upper() != scheme:
            problems.append(f"its scheme is {scheme} but the ticket's protocol is {protocol or 'missing'}")
        if port is not None and ports != [str(port)]:
            problems.append(f"it states port {port} but the ticket's ports are {', '.join(ports) or 'missing'}")
        if problems:
            out.append({"where": f"destination/{i}/url", "url": url, "port": port,
                        "message": f"{url}: " + " and ".join(problems) + ". The rule takes one protocol and port, "
                                   "and the workflow will not pick them; edit the ticket so the URL, protocol and ports "
                                   "agree."})
    return out
