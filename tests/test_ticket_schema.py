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
    ticket["sources"] = [{"cidr": "203.0.113.16/28"}]
    ticket["destination"] = [{"environment": "prod", "site": "primary", "cidr": "10.100.20.14/32"}]
    ticket["ports"] = ["22"]
    return ticket


@pytest.mark.parametrize("path", sorted(TICKETS.glob("*.yaml")), ids=lambda p: p.name)
def test_every_sample_ticket_is_valid(path):
    assert ticket_errors(load_ticket(path)) == []


def test_valid_inbound_ticket(ticket):
    assert ticket_errors(inbound(ticket)) == []


def test_valid_remove_ticket(ticket):
    ticket["item"] = "Firewall Rule Removal"
    ticket["existing_rule"] = "https-sett-to-northwindFs"
    assert ticket_errors(ticket) == []


def test_partner_ip_group_is_valid(ticket):
    ticket["destination"] = [{"ip_group": "ipg-partner-northwind"}]
    assert ticket_errors(ticket) == []


def test_wide_but_well_formed_requests_pass_the_schema(ticket):
    # The schema checks shape. Catching any/any is Tier 1's job, so the eval
    # set must be able to hold tickets like this one.
    ticket["destination"] = [{"cidr": "0.0.0.0/0"}]
    ticket["ports"] = ["*"]
    assert ticket_errors(ticket) == []


@pytest.mark.parametrize("url", ["https://www.google.com/search?q=x", "http://www.cnn.com",
                                 "https://Files.Northwind.example:8443/upload/v1", "https://api.northwind.example/"])
def test_destination_url_passes_the_schema(ticket, url):
    ticket["destination"] = [{"url": url}]
    assert ticket_errors(ticket) == []


@pytest.mark.parametrize("address", [{"vnet": "vnet-prod-app", "subnet": "snet-backend"}, {"vnet": "vnet-prod-data"}])
def test_a_vnet_named_without_an_address_passes_the_schema(ticket, address):
    # The shape is kept so intake can save the ticket for engineer review; intake, not the schema, blocks it.
    ticket["destination"] = [address]
    assert ticket_errors(ticket) == []


@pytest.mark.parametrize("fqdn", ["*", "*.com", "*.northwind.example"])
def test_wildcard_fqdns_pass_the_schema(ticket, fqdn):
    # STD-COLL-02 flags these as cautions; the schema must let them through.
    ticket["destination"] = [{"fqdn": fqdn}]
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
    "partner IP group in capitals": lambda t: t["destination"].__setitem__(0, {"ip_group": "ipg-partner-Northwind"}),
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
    "public_port field": lambda t: t.update(public_port="2222"),
    "existing rule on add": lambda t: t.update(existing_rule="https-sett-to-northwindFs"),
    "unknown catalog item": lambda t: t.update(item="Firewall Rule Change"),
    # Real tickets carry neither field: the catalog item says add or remove,
    # and the addresses say egress or inbound.
    "change_type field": lambda t: t.update(change_type="add_rule"),
    "direction field": lambda t: t.update(direction="egress"),
    "bad ticket number": lambda t: t.update(number="REQ-0042"),
    "empty justification": lambda t: t.update(justification=""),
    "url as a source": lambda t: t["sources"].__setitem__(0, {"url": "https://www.cnn.com/"}),
    "subnet without its vnet": lambda t: t["destination"].__setitem__(0, {"cidr": "10.100.16.0/24", "subnet": "snet-database"}),
    "vnet name without vnet- prefix": lambda t: t["destination"].__setitem__(0, {"vnet": "prod-data"}),
    "vnet and cidr together": lambda t: t["destination"].__setitem__(
        0, {"vnet": "vnet-prod-data", "cidr": "10.100.16.0/24"}),
    "url and fqdn together": lambda t: t["destination"].__setitem__(
        0, {"url": "https://www.cnn.com/", "fqdn": "www.cnn.com"}),
    "url with ftp scheme": lambda t: t["destination"].__setitem__(0, {"url": "ftp://www.cnn.com/"}),
    "url with no scheme": lambda t: t["destination"].__setitem__(0, {"url": "www.cnn.com/world"}),
    "url with wildcard host": lambda t: t["destination"].__setitem__(0, {"url": "https://*.cnn.com/"}),
    "url with IP host": lambda t: t["destination"].__setitem__(0, {"url": "https://10.1.2.3/"}),
    "url with user and password": lambda t: t["destination"].__setitem__(0, {"url": "https://user:pw@localhost/"}),
    "url with port above 65535": lambda t: t["destination"].__setitem__(0, {"url": "https://www.cnn.com:70000/"}),
    "url with a space": lambda t: t["destination"].__setitem__(0, {"url": "https://www.cnn.com/a b"}),
    "no change_sites": lambda t: t.pop("change_sites"),
    "empty site list": lambda t: t["change_sites"].update(prod=[]),
    "unknown site": lambda t: t["change_sites"].update(prod=["west"]),
    "site listed twice": lambda t: t["change_sites"].update(prod=["primary", "primary"]),
    "change_sites misses an environment": lambda t: t["change_sites"].pop("lab"),
    "change_sites names an extra environment": lambda t: (t["environments"].remove("lab"), t["dr_site_built"].pop("lab")),
    "dr_site_built misses an environment": lambda t: t["dr_site_built"].pop("lab"),
    "DR change where DR is not built": lambda t: t["dr_site_built"].update(prod=False),
    "IP group at another site than its name": lambda t: t["sources"].__setitem__(
        0, {"environment": "lab", "site": "primary", "ip_group": "ipg-sett-lab-dr"}),
    "IP group in another environment": lambda t: t["sources"].__setitem__(
        0, {"environment": "lab", "site": "primary", "ip_group": "ipg-sett-dev"}),
    "internal IP group with no env-site": lambda t: t["destination"].append({"ip_group": "ipg-sett-prod"}),
    "partner IP group given an env-site": lambda t: t["destination"].__setitem__(
        0, {"environment": "prod", "site": "primary", "ip_group": "ipg-partner-northwind"}),
    "on-prem IP group tied to an Azure site": lambda t: t["sources"].__setitem__(
        0, {"environment": "lab", "site": "primary", "ip_group": "ipg-onprem-primary"}),
    "unknown on-prem site": lambda t: t["sources"].__setitem__(0, {"ip_group": "ipg-onprem-tertiary"}),
    "on-prem CIDR at an unknown location": lambda t: t["sources"].__setitem__(
        0, {"location": "onprem-tertiary", "cidr": "172.20.20.0/24"}),
    "on-prem CIDR also given an Azure site": lambda t: t["sources"].__setitem__(
        0, {"location": "onprem-primary", "environment": "prod", "site": "primary", "cidr": "172.20.20.0/24"}),
    "location on an IP group": lambda t: t["sources"].__setitem__(
        0, {"location": "onprem-primary", "ip_group": "ipg-onprem-primary"}),
    "location on a hostname": lambda t: t["destination"].__setitem__(
        0, {"location": "onprem-primary", "fqdn": "intranet.contoso.example"}),
}


@pytest.mark.parametrize("mutate", BAD.values(), ids=BAD.keys())
def test_bad_ticket_is_refused(ticket, mutate):
    mutate(ticket)
    assert ticket_errors(ticket) != []


@pytest.mark.parametrize("sites", [["primary"], ["dr"], ["primary", "dr"]], ids=["primary", "dr", "both"])
def test_each_scope_is_valid_where_dr_is_built(ticket, sites):
    ticket["change_sites"]["prod"] = sites
    assert ticket_errors(ticket) == []


def test_primary_only_is_valid_where_dr_is_not_built(ticket):
    # Separate answers: DR may be absent, and the ticket still changes primary.
    ticket["dr_site_built"]["prod"] = False
    ticket["change_sites"]["prod"] = ["primary"]
    assert ticket_errors(ticket) == []


def test_egress_icmp_is_valid(ticket):
    # Only inbound is limited to TCP or UDP.
    ticket["protocol"] = "ICMP"
    ticket["ports"] = ["*"]
    assert ticket_errors(ticket) == []


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


def test_ip_groups_at_their_own_env_site_are_valid(ticket):
    """An internal group at the site its name says, and a partner group with no env-site, both pass."""
    first = ticket["sources"][0]
    env, site = first["environment"], first["site"]
    ticket["sources"][0] = {"environment": env, "site": site, "ip_group": f"ipg-sett-{env}{'-dr' if site == 'dr' else ''}"}
    ticket["destination"] = [{"ip_group": "ipg-partner-northwind"}]
    assert ticket_errors(ticket) == []


@pytest.mark.parametrize("side", ["sources", "destination"])
def test_both_on_prem_groups_may_be_named_on_either_side(ticket, side):
    """Either on-prem group, or both, as source or destination, with no Azure site attached."""
    ticket[side] = [{"ip_group": "ipg-onprem-primary"}, {"ip_group": "ipg-onprem-secondary"}]
    assert ticket_errors(ticket) == []


def onprem_to_azure(ticket, source):
    """Turn the sample into on-prem users reaching an Azure spoke on HTTPS."""
    ticket["sources"] = [source]
    ticket["destination"] = [{"environment": "prod", "site": "primary", "cidr": "10.100.17.0/24"}]
    ticket["environments"], ticket["dr_site_built"], ticket["change_sites"] = ["prod"], {"prod": True}, {"prod": ["primary"]}
    ticket["protocol"], ticket["ports"], ticket["partner"] = "HTTPS", ["443"], None
    return ticket


@pytest.mark.parametrize("source", [{"location": "onprem-primary", "cidr": "172.20.20.0/24"},
                                    {"location": "onprem-secondary", "cidr": "172.24.96.0/24"},
                                    {"ip_group": "ipg-onprem-primary"}], ids=["primary CIDR", "secondary CIDR", "group"])
def test_onprem_source_is_internal_not_inbound(ticket, source):
    """An on-prem source is internal, so HTTPS is allowed; only a fully external source is inbound DNAT."""
    assert ticket_errors(onprem_to_azure(ticket, source)) == []


def test_external_source_with_https_is_still_inbound_and_refused(ticket):
    """The same ticket from a partner range is inbound DNAT, which takes TCP or UDP only."""
    assert ticket_errors(onprem_to_azure(ticket, {"cidr": "203.0.113.16/28"})) != []
