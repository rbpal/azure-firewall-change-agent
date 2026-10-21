"""Intake: list what an engineer must review before a ticket goes to the agent.

Example: a source of `172.20.20.15/24` gives one finding, `invalid_address`, that
names both readings: the host 172.20.20.15/32 (1 address) or the subnet
172.20.20.0/24 (256 addresses). The ticket is saved as awaiting review.

Why: the workflow never rejects a ticket. A problem pauses it for the engineer,
who rejects it, edits it, or accepts it. Code catches what is malformed here, so
the agent only ever sees a ticket that passes every check.

Safety rule: intake never changes the ticket. It never picks a reading, never
normalises an address and never fills in a missing one. A suggestion from the
network data is shown with its file, and only an engineer's edit puts a value on
the ticket. A finding marked not acceptable can be cleared only by an edit.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
from pathlib import Path

import yaml

from workflow.tickets import ticket_errors

ADDRESS_PLAN = "data/network/address-plan.yaml"
SIDES = ("sources", "destination")

# Findings an engineer may accept as they stand. Every other code needs an edit, because
# the ticket is malformed or contradicts itself and accepting it would leave a guess.
ACCEPTABLE = {"wider_than_plan", "planned_address", "address_not_in_plan", "skip_approval_requested"}
NEEDS_PLANNED = {"planned_address", "address_not_in_plan"}  # accepting these needs the engineer's planned-address record

# ASCII digits only, matched against the whole text: \d would accept other scripts' digits
# and $ would accept a trailing newline.
_CIDR_SHAPE = re.compile(r"([0-9]+)\.([0-9]+)\.([0-9]+)\.([0-9]+)/([0-9]+)")


def ticket_version(ticket: dict) -> str:
    """The SHA-256 of the ticket's fields in a fixed order: any change to any value gives a new version."""
    return hashlib.sha256(json.dumps(ticket, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def finding(code: str, where: str, message: str, **extra) -> dict:
    """One review finding: a code, the ticket field it concerns, a plain message, and whether it can be accepted."""
    return {"code": code, "where": where, "message": message, "acceptable": code in ACCEPTABLE, **extra}


def cidr_finding(where: str, text) -> dict | None:
    """Explain why a ticket CIDR cannot be used as written, or return None when it is a valid network."""
    if not isinstance(text, str):
        return finding("invalid_address", where, f"{text!r} is not an IPv4 CIDR")
    m = _CIDR_SHAPE.fullmatch(text)
    if not m:
        return finding("invalid_address", where, f"{text!r} is not written as an IPv4 CIDR, such as 10.104.14.0/24")
    if any(len(n) > 1 and n.startswith("0") for n in m.groups()):
        return finding("invalid_address", where,
                       f"{text}: a number has a leading zero, which some tools read as octal. "
                       "The workflow will not drop it; edit the ticket with the intended value.")
    octets, prefix = [int(x) for x in m.groups()[:4]], int(m.group(5))
    if any(o > 255 for o in octets):
        return finding("invalid_address", where, f"{text}: each of the four numbers must be 0 to 255")
    if prefix > 32:
        return finding("invalid_address", where,
                       f"{text}: an IPv4 address has 32 bits, so the prefix length can be at most /32. "
                       "Ask the requester for the intended range; the workflow will not guess one.")
    try:
        ipaddress.IPv4Network(text, strict=True)
        return None
    except ValueError:
        host = text.split("/")[0]
        try:
            net = ipaddress.IPv4Network(text, strict=False)
        except ValueError as error:  # every known shape is caught above; never crash on one that is not
            return finding("invalid_address", where, f"{text!r} is not a valid IPv4 CIDR ({error})")
        return finding("invalid_address", where,
                       f"{text} has host bits set, so it has two readings: the host {host}/32 (1 address) "
                       f"or the subnet {net} ({net.num_addresses} addresses). The workflow will not pick one; "
                       "edit the ticket with the intended value.",
                       readings=[f"{host}/32", str(net)])


def vnet_suggestions(repo: Path, vnet: str) -> list[dict]:
    """Address-plan ranges whose VNet name equals, or else starts with, the name on the ticket."""
    ranges = yaml.safe_load((Path(repo) / ADDRESS_PLAN).read_text())["ranges"]
    named = [r for r in ranges if r.get("vnet")]
    hits = [r for r in named if r["vnet"] == vnet] or [r for r in named if r["vnet"].startswith(vnet)]
    return [{"cidr": r["cidr"], "environment": r["environment"], "site": r["site"], "vnet": r["vnet"],
             "spoke": r.get("spoke"), "source": ADDRESS_PLAN} for r in hits]


def missing_address_finding(repo: Path, where: str, address: dict) -> dict:
    """A VNet or subnet named with no CIDR: say what is missing and show possible mappings, never substitute one."""
    vnet, subnet = address.get("vnet"), address.get("subnet")
    named = " / ".join(x for x in (vnet, subnet) if x)
    suggestions = vnet_suggestions(repo, vnet) if vnet else []
    parts = [f"{named} names a network but gives no IP address or CIDR, so no rule can be written for it."]
    if subnet:
        parts.append(f"{ADDRESS_PLAN} records no subnet names, so {subnet} cannot be mapped.")
    if not suggestions:
        parts.append(f"No VNet named {vnet} is in {ADDRESS_PLAN}.")
    elif len(suggestions) == 1:
        parts.append(f"Possible mapping, not applied: {suggestions[0]['cidr']} ({suggestions[0]['vnet']}, "
                     f"{suggestions[0]['environment']} {suggestions[0]['site']}) from {ADDRESS_PLAN}.")
    else:
        parts.append(f"{len(suggestions)} VNets in {ADDRESS_PLAN} start with {vnet}, across environments or sites; "
                     "none is applied.")
    parts.append("Edit the ticket with the confirmed CIDR or IP group.")
    return finding("missing_address", where, " ".join(parts), suggestions=suggestions)


def intake_findings(repo: Path, ticket: dict) -> list[dict]:
    """Every problem an engineer must review before the agent sees the ticket; empty means it may go on."""
    if not isinstance(ticket, dict):
        return [finding("invalid_ticket", "(ticket)", "the file does not hold a ticket")]
    out, explained = [], set()
    for side in SIDES:
        entries = ticket.get(side)
        for i, address in enumerate(entries if isinstance(entries, list) else []):
            where = f"{side}/{i}"
            if not isinstance(address, dict):
                continue
            if "cidr" in address and (f := cidr_finding(f"{where}/cidr", address["cidr"])):
                out.append(f)
                explained.add(where)
            elif "vnet" in address or "subnet" in address:
                out.append(missing_address_finding(repo, where, address))
                explained.add(where)
    for error in ticket_errors(ticket):
        path = error.split(":", 1)[0]
        if not any(path == w or path.startswith(w + "/") for w in explained):
            out.append(finding("invalid_ticket", path, error))
    return out
