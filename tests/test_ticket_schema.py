"""Ticket schema and validator. Every check here must be able to fail."""

import copy
from pathlib import Path

import pytest

from workflow.tickets import load_ticket, ticket_errors

TICKETS = Path(__file__).resolve().parent.parent / "data" / "tickets"


@pytest.fixture
def ticket():
    return copy.deepcopy(load_ticket(TICKETS / "RITM0010042.yaml"))


def inbound(ticket):
    ticket["direction"] = "inbound"
    ticket["sources"] = [{"cidr": "203.0.113.16/28"}]
    ticket["destination"] = [{"environment": "prod", "site": "primary", "cidr": "10.100.20.14/32"}]
    ticket["ports"] = ["22"]
    ticket["public_port"] = "2222"
    return ticket


@pytest.mark.parametrize("path", sorted(TICKETS.glob("*.yaml")), ids=lambda p: p.name)
def test_every_sample_ticket_is_valid(path):
    assert ticket_errors(load_ticket(path)) == []


def test_valid_inbound_ticket(ticket):
    assert ticket_errors(inbound(ticket)) == []


def test_valid_remove_ticket(ticket):
    ticket["change_type"] = "remove_rule"
    ticket["existing_rule"] = "https-sett-to-northwindFs"
    assert ticket_errors(ticket) == []


def test_wide_but_well_formed_requests_pass_the_schema(ticket):
    # The schema checks shape. Catching any/any is Tier 1's job, so the eval
    # set must be able to hold tickets like this one.
    ticket["destination"] = [{"cidr": "0.0.0.0/0"}]
    ticket["ports"] = ["*"]
    assert ticket_errors(ticket) == []


BAD = {
    "bad CIDR octet": lambda t: t["sources"][0].update(cidr="10.106.300.0/24"),
    "CIDR host bits set": lambda t: t["sources"][0].update(cidr="10.106.14.5/24"),
    "address with two types": lambda t: t["destination"][0].update(fqdn="files.northwind.example"),
    "address with no type": lambda t: t["destination"].__setitem__(0, {}),
    "environment without site": lambda t: t["sources"][0].pop("site"),
    "unknown environment": lambda t: t["environments"].append("qa"),
    "IP group with unknown environment": lambda t: t["sources"].__setitem__(
        0, {"environment": "lab", "site": "primary", "ip_group": "ipg-sett-uat"}
    ),
    "port above 65535": lambda t: t.update(ports=["70000"]),
    "port range high to low": lambda t: t.update(ports=["9000-8000"]),
    "port zero": lambda t: t.update(ports=["0"]),
    "opened not a date-time": lambda t: t.update(opened="yesterday"),
    "two approvals": lambda t: t["approvals"].pop(),
    "duplicate approval group": lambda t: t["approvals"][2].update(group="security"),
    "approved ticket with pending approval": lambda t: t["approvals"][0].update(state="pending"),
    "unknown partner": lambda t: t.update(partner="Globex"),
    "unknown field": lambda t: t.update(priority="high"),
    # Temporary rules never come through a ticket, so the fields are refused.
    "temporary field": lambda t: t.update(temporary=True),
    "public port on egress": lambda t: t.update(public_port="2222"),
    "existing rule on add": lambda t: t.update(existing_rule="https-sett-to-northwindFs"),
    "bad ticket number": lambda t: t.update(number="REQ-0042"),
    "empty justification": lambda t: t.update(justification=""),
}


@pytest.mark.parametrize("mutate", BAD.values(), ids=BAD.keys())
def test_bad_ticket_is_refused(ticket, mutate):
    mutate(ticket)
    assert ticket_errors(ticket) != []


def test_inbound_without_public_port_is_refused(ticket):
    t = inbound(ticket)
    del t["public_port"]
    assert ticket_errors(t) != []


def test_inbound_icmp_is_refused(ticket):
    t = inbound(ticket)
    t["protocol"] = "ICMP"
    assert ticket_errors(t) != []


def test_unquoted_yaml_timestamp_is_refused(tmp_path):
    # PyYAML turns an unquoted timestamp into a datetime object, not a string.
    text = (TICKETS / "RITM0010042.yaml").read_text().replace(
        'opened: "2026-10-07T09:12:00-04:00"', "opened: 2026-10-07T09:12:00-04:00"
    )
    path = tmp_path / "t.yaml"
    path.write_text(text)
    assert any(e.startswith("opened") for e in ticket_errors(load_ticket(path)))
