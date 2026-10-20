"""Load a YAML ticket and check it before the workflow uses it.

Two layers. The JSON Schema in data/tickets/schema.json checks shape. The
code below checks what a pattern cannot: a CIDR with host bits set, a port
outside 1-65535, a range that runs high to low, an IP group placed at another
env-site than its name says, scope answers that do not cover
exactly the ticket's environments, and a DR change asked for where the ticket
itself says DR is not built. Meaning (does this source
belong to this environment?) is checked later, against the address plan.
"""

from __future__ import annotations

import ipaddress
import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "data" / "tickets" / "schema.json"

_validator = Draft202012Validator(
    json.loads(SCHEMA_PATH.read_text()),
    format_checker=Draft202012Validator.FORMAT_CHECKER,
)


def load_ticket(path: str | Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def _ip_group_errors(where: str, address: dict) -> list[str]:
    """An internal group must sit at the env-site its name says; partner and on-prem groups have no env-site."""
    name = address["ip_group"]
    if name.startswith(("ipg-partner-", "ipg-onprem-")):  # usable at any selected Azure site
        kind = "partner" if name.startswith("ipg-partner-") else "on-prem"
        return [f"{where}: {kind} group {name} is outside every env-site, so it takes no environment or site"] \
            if "environment" in address else []
    env, dr = name.split("-")[2], name.endswith("-dr")
    if "environment" not in address:
        return [f"{where}: internal group {name} needs its environment and site"]
    site = "dr" if dr else "primary"
    if (address["environment"], address["site"]) != (env, site):
        return [f"{where}: {name} belongs to {env} {site}, not {address['environment']} {address['site']}"]
    return []


def ticket_errors(ticket: dict) -> list[str]:
    """Every problem with the ticket, as readable strings. Empty means valid."""
    errors = [
        f"{'/'.join(str(p) for p in e.absolute_path) or '(ticket)'}: {e.message}"
        for e in sorted(_validator.iter_errors(ticket), key=lambda e: list(e.absolute_path))
    ]
    if errors:
        return errors  # later checks assume the shape is right

    for field in ("sources", "destination"):
        for i, address in enumerate(ticket[field]):
            if "cidr" in address:
                try:
                    ipaddress.IPv4Network(address["cidr"], strict=True)
                except ValueError as e:
                    errors.append(f"{field}/{i}/cidr: {e}")
            if "ip_group" in address:
                errors += _ip_group_errors(f"{field}/{i}", address)

    envs = set(ticket["environments"])
    for field in ("dr_site_built", "change_sites"):
        if set(ticket[field]) != envs:
            errors.append(f"{field}: answers {sorted(ticket[field])}, ticket names {sorted(envs)}")
    for env, sites in ticket["change_sites"].items():
        if "dr" in sites and ticket["dr_site_built"].get(env) is False:
            errors.append(f"change_sites/{env}: asks for a DR change, but dr_site_built says {env} DR is not built")

    for port in ticket["ports"]:
        if port == "*":
            continue
        low, _, high = port.partition("-")
        low, high = int(low), int(high or low)
        if high > 65535:
            errors.append(f"ports: {port} is above 65535")
        elif low > high:
            errors.append(f"ports: {port} runs high to low")

    return errors
