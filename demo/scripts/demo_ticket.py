"""Shared parts of the three step 1 scripts: the fixed ticket fields, the address checks and the write.

Example: step_01_01_make_demo_network_ticket.py builds its ticket with build(), then main() calls run(), which
writes demo/01-waiting/<number>.yaml.

Why: the network, application and DNAT tickets differ only in their addresses; one copy of the rest keeps them alike.

Safety rule: run() writes one file, only when no check fails, and never overwrites. It never calls Foundry or Azure.
"""

# ===== FIXED SETTINGS =====
ASSIGNEE = "your-github-login"  # the engineer who works the ticket
SITES = {"primary": "eastus2", "dr": "centralus"}  # dev site -> region
APPROVALS = [
    {"group": "security", "approver": "Sam Ortiz", "state": "approved"},
    {"group": "network", "approver": "Lee Chen", "state": "approved"},
    {"group": "project", "approver": "Dana Brooks", "state": "approved"},
]

import ipaddress  # noqa: E402
import re  # noqa: E402
import sys  # noqa: E402
from datetime import datetime  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from workflow.intake import intake_findings  # noqa: E402

DEMO = REPO / "demo"


def now() -> str:
    """Return the Mac's current local time to the second, with its UTC offset."""
    return datetime.now().astimezone().isoformat(timespec="seconds")


def dev(site: str, cidr: str) -> dict:
    """Return an internal dev address at this site."""
    return {"environment": "dev", "site": site, "cidr": cidr}


def build(number, opened, requested_for, sources, destination, protocol, ports, justification) -> dict:
    """Return a dev ticket for both sites, approved and assigned to ASSIGNEE."""
    return {
        "number": number,
        "item": "Firewall Change Request",
        "state": "approved",
        "requested_for": requested_for,
        "opened": opened,
        "environments": ["dev"],
        "dr_site_built": {"dev": True},
        "change_sites": {"dev": list(SITES)},
        "sources": sources,
        "destination": destination,
        "protocol": protocol,
        "ports": list(ports),
        "justification": justification,
        "approvals": APPROVALS,
        "assigned_to": ASSIGNEE,
    }


def text(ticket: dict) -> str:
    """Return the ticket as demo YAML: a synthetic-data header, then one short list or map per line."""
    body = yaml.safe_dump(ticket, sort_keys=False, default_flow_style=None, width=1000)
    return "# Fictitious demo ticket. All names and addresses are synthetic.\n" + body


def dev_ranges(site: str, kind: str | None = None) -> list[str]:
    """Return the address plan's dev CIDRs at this site and its region, optionally of one kind."""
    plan = yaml.safe_load((REPO / "data/network/address-plan.yaml").read_text())["ranges"]
    return [r["cidr"] for r in plan if r.get("environment") == "dev" and r.get("site") == site
            and r.get("region") == SITES[site] and kind in (None, r.get("kind"))]


def subnet_problems(addresses: list[dict]) -> list[str]:
    """List every dev address that is not exactly a range in the address plan at its site."""
    return [f"{a['cidr']} is not in the address plan at dev {a['site']}"
            for a in addresses if a["cidr"] not in dev_ranges(a["site"])]


def host_problems(addresses: list[dict]) -> list[str]:
    """List every dev address that is not one host inside a dev spoke subnet at its site."""
    found = []
    for a in addresses:
        host = ipaddress.ip_network(a["cidr"])
        if host.prefixlen != 32:
            found.append(f"{a['cidr']} must be one host (/32)")
        elif not any(host.subnet_of(ipaddress.ip_network(r)) for r in dev_ranges(a["site"], "spoke")):
            found.append(f"{a['cidr']} is not inside a dev spoke subnet at {a['site']}")
    return found


def run(build_ticket, problems, argv: list[str] | None = None) -> int:
    """Build the ticket at the current time, check it, and write it to 01-waiting if nothing is wrong."""
    if (sys.argv[1:] if argv is None else argv):
        print("No arguments: set the values at the top of the file. Nothing was written.")
        return 2
    ticket = build_ticket(now())
    number = ticket["number"]
    if not re.fullmatch(r"RITM\d{7}", number):
        print(f"Set TICKET_NUMBER at the top first: RITM followed by 7 digits, not {number!r}. Nothing was written.")
        return 2
    found = [f"{number} is already used: {p.relative_to(DEMO)}" for p in DEMO.rglob(f"*{number}*")]
    found += problems(ticket)
    found += [f"{f['code']} {f['where']}: {f['message']}" for f in intake_findings(REPO, ticket) if not f["acceptable"]]
    if found:
        print(f"Stopped: {number} not written.", *found, sep="\n  ")
        return 1
    path = DEMO / "01-waiting" / f"{number}.yaml"
    with path.open("x") as out:
        out.write(text(ticket))
    print(f"Created {path}. Not submitted.")
    return 0
