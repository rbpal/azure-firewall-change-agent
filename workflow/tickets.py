"""Load a YAML ticket and check it before the workflow uses it.

Two layers. The JSON Schema in data/tickets/schema.json checks shape. The
code below checks what a pattern cannot: a CIDR with host bits set, a port
outside 1-65535, a range that runs high to low. Meaning (does this source
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

    ports = list(ticket["ports"])
    if "public_port" in ticket:
        ports.append(ticket["public_port"])
    for port in ports:
        if port == "*":
            continue
        low, _, high = port.partition("-")
        low, high = int(low), int(high or low)
        if high > 65535:
            errors.append(f"ports: {port} is above 65535")
        elif low > high:
            errors.append(f"ports: {port} runs high to low")

    return errors
