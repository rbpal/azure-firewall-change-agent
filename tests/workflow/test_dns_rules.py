"""Exact FQDNs drafted as network rules to the addresses DNS returned, and the scope checks those addresses pass.

The ticket is the prod primary-only sett ticket from test_scope.py (source 10.100.14.0/24 at prod-eastus2), given an
FQDN destination. The reply is what the agent drafts after dns_lookup_for_fqdn answered. Addresses come from the
synthetic plan: 192.0.2.x is public (documentation range, outside the plan). Every check here must be able to fail.
"""

import copy

import pytest
import yaml

from workflow.scope import ApprovalError, apply_reply, plan_writes
from tests.workflow.test_scope import PRIMARY, SPOKE_FILE, changed, flow_reply, flow_ticket, repo, snapshot  # noqa: F401

FQDN = {"fqdn": "www.google.com"}
INTERNAL = {"fqdn": "reports.internal.example"}
ONPREM = {"fqdn": "erp.corp.example"}


def answer(host, *addresses, resolves=True):
    """One dns_lookup_for_fqdn answer as the Foundry response carries it."""
    return {"host": host, "resolves": resolves, "a": list(addresses), "aaaa": [], "resolver": "168.63.129.16"}


def write(repo, ticket, reply, answers=None):
    """apply_reply with the response's DNS answers: by default, the one answer that gives exactly the reply's addresses."""
    if answers is None:
        given = ticket["destination"][0]
        name = given.get("fqdn") or (given["url"].split("/")[2] if "url" in given else None)
        answers = [answer(name, *[d.split("/")[0] for d in reply["rules"][0]["destinations"]])] if name else []
    return apply_reply(repo, ticket, reply, dns_answers=answers)


def drafted(*destinations, protocol="TCP", ports=("443",)):
    """The agent's primary-site draft to these resolved addresses."""
    r = flow_reply(protocol, ports)
    r["rules"][0]["destinations"] = list(destinations)
    return r


def refused(repo, ticket, reply, why, answers=None):
    """Assert the draft is refused for `why` and writes nothing."""
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match=why):
        write(repo, ticket, reply, answers)
    assert changed(before, repo) == set()


@pytest.mark.parametrize("addresses", [["192.0.2.80"], ["192.0.2.80", "192.0.2.81"], ["192.0.2.80/32"]],
                         ids=["one address", "two addresses", "written as /32"])
def test_public_resolved_addresses_become_a_tcp_443_network_rule(repo, addresses):
    before = snapshot(repo)
    write(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(*addresses))
    assert changed(before, repo) == {SPOKE_FILE.format(PRIMARY)}
    text = (repo / SPOKE_FILE.format(PRIMARY)).read_text()
    assert all(a.split("/")[0] in text for a in addresses) and "www.google.com" not in text


def test_a_url_destination_is_handled_like_its_fqdn(repo):
    before = snapshot(repo)
    write(repo, flow_ticket("HTTPS", ["443"], {"url": "https://www.google.com/"}), drafted("192.0.2.80"))
    assert changed(before, repo) == {SPOKE_FILE.format(PRIMARY)}


@pytest.mark.parametrize("protocol, ports", [("UDP", ["53"]), ("TCP", ["5671"]), ("HTTP", ["80"])])
def test_the_tickets_transport_and_ports_are_kept_and_http_becomes_tcp(repo, protocol, ports):
    rule_protocol = "TCP" if protocol == "HTTP" else protocol
    write(repo, flow_ticket(protocol, ports, FQDN), drafted("192.0.2.80", protocol=rule_protocol, ports=ports))


def test_https_kept_as_https_to_resolved_addresses_is_refused(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80", protocol="HTTPS"),
            "HTTP and HTTPS to addresses become a TCP network rule")


def test_a_wider_port_than_the_ticket_is_still_refused(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80", ports=["443", "8443"]), "port 8443 is not within")


def test_an_address_is_accepted_only_when_the_ticket_gives_an_exact_fqdn(repo):
    """Without an FQDN on the ticket, an address the ticket does not give is unapproved, as before."""
    refused(repo, flow_ticket("TCP", ["443"]), drafted("192.0.2.80"), "is not on the ticket")


def test_a_wildcard_domain_pattern_does_not_approve_addresses(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], {"fqdn": "*.google.com"}), drafted("192.0.2.80"),
            "192.0.2.80 is a CIDR, a type the ticket does not approve here")


def test_a_resolved_cidr_wider_than_one_host_is_refused(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.0/24"),
            "192.0.2.0/24 is a CIDR, a type the ticket does not approve here")


def test_the_exact_fqdn_itself_is_refused_in_the_rule(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("www.google.com"), "www.google.com is an exact FQDN")


@pytest.mark.parametrize("address", ["0.0.0.1", "127.0.0.1", "169.254.10.10", "224.0.0.5", "240.0.0.1", "255.255.255.255"])
def test_a_never_allowed_address_stops_as_dns_lookup_failed(repo, address):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(address), f"{address} is a .*dns_lookup_failed")


def test_an_internal_address_at_the_rules_own_env_site_is_allowed(repo):
    """Private is not refused for being private: 10.100.15.10 is prod-eastus2's rprt spoke, the rule's own env-site."""
    before = snapshot(repo)
    write(repo, flow_ticket("HTTPS", ["443"], INTERNAL), drafted("10.100.15.10"))
    assert changed(before, repo) == {SPOKE_FILE.format(PRIMARY)}


def test_an_onprem_address_is_allowed(repo):
    write(repo, flow_ticket("HTTPS", ["443"], ONPREM), drafted("172.20.10.5"))


def test_an_address_at_the_other_site_returns_the_ticket_naming_the_missing_routing_fact(repo):
    """10.101.15.10 is prod-centralus. routing.yaml records no path between hubs, so the firewalls are not established."""
    refused(repo, flow_ticket("HTTPS", ["443"], INTERNAL), drafted("10.101.15.10"),
            r"10.101.15.10 sits at prod-centralus.*records no path between hubs.*afw-hub-prod-centralus.*"
            "needs_engineer_review")


def test_an_address_in_another_environment_is_env_mismatch(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], INTERNAL), drafted("10.102.15.10"),
            "10.102.15.10 sits in stage-eastus2, environment stage, not the ticket's prod.*env_mismatch")


@pytest.mark.parametrize("address", ["192.168.50.5", "100.64.1.1"], ids=["private", "shared"])
def test_a_private_or_shared_address_outside_the_plan_is_address_not_in_plan(repo, address):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(address), f"{address} is a private or shared.*address_not_in_plan")


def test_an_address_no_spoke_owns_is_planned_address(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("10.100.200.5"), "10.100.200.5 is inside prod-eastus2.*planned_address")


def test_a_source_whose_spoke_has_no_internet_next_hop_is_not_on_the_path(repo):
    """With sett's internet route removed from routing.yaml, the rule's firewall is not on the source's path."""
    path = repo / "data" / "network" / "routing.yaml"
    data = yaml.safe_load(path.read_text())
    data["env_sites"][PRIMARY]["spokes"]["sett"]["for"] = ["private"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80"),
            "does not reach afw-hub-prod-eastus2 as routing.yaml's internet next hop")
    write(repo, flow_ticket("HTTPS", ["443"], INTERNAL), drafted("10.100.15.10"))  # private still is


def test_a_removal_of_an_existing_exact_fqdn_application_rule_is_still_written(repo):
    """The estate keeps rules that name FQDNs; a removal matches the stored rule, so it is not refused."""
    from tests.workflow.test_cli import request  # noqa: F401
    from workflow.tickets import load_ticket
    from tests.workflow.test_scope import REPO
    ticket = load_ticket(REPO / "data" / "tickets" / "RITM0010044.yaml")
    rule = {"env_site": "dev-eastus2", "spoke": "sett", "collection": "allow-sett-app-rules",
            "name": "https-sett-to-northwindApi", "sources": ["ipg-sett-dev"], "destinations": ["api.northwind.example"],
            "ports": ["443"], "protocol": "HTTPS"}
    dr = copy.deepcopy(rule) | {"env_site": "dev-centralus", "sources": ["ipg-sett-dev-dr"]}
    assert len(plan_writes(repo, ticket, {"outcome": "draft", "action": "remove", "rules": [rule, dr]})) == 2


# The draft check reads the DNS tool's answer from the same Foundry response; it never looks the name up itself.

def test_with_no_dns_answer_in_the_response_no_address_is_accepted(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80"),
            "no successful dns_lookup_for_fqdn answer for www.google.com in this draft's response", answers=[])


def test_a_failed_lookup_approves_no_address(repo):
    """NXDOMAIN, or a name with no A record, is not a successful answer, so a drafted address is refused."""
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80"), "no successful dns_lookup_for_fqdn answer",
            answers=[answer("www.google.com", resolves=False)])
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80"), "no successful dns_lookup_for_fqdn answer",
            answers=[{"host": "www.google.com", "resolves": True, "a": [], "aaaa": ["2001:db8::1"]}])


def test_an_address_the_tool_did_not_return_is_refused(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80", "192.0.2.99"),
            "destination 192.0.2.99 is not an address dns_lookup_for_fqdn returned", answers=[answer("www.google.com", "192.0.2.80")])


def test_a_returned_address_left_out_of_the_rule_is_refused(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80"),
            "destination 192.0.2.81, returned by dns_lookup_for_fqdn for www.google.com, is missing",
            answers=[answer("www.google.com", "192.0.2.80", "192.0.2.81")])


def test_only_the_first_successful_answer_counts_and_answers_are_never_combined(repo):
    first, later = answer("www.google.com", "192.0.2.80"), answer("www.google.com", "192.0.2.90")
    assert plan_writes(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80"), dns_answers=[first, later])
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.90"), "192.0.2.90 is not an address", [first, later])
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80", "192.0.2.90"), "192.0.2.90 is not an address",
            [first, later])
    assert plan_writes(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.90"),
                       dns_answers=[answer("www.google.com", resolves=False), later])  # a failed lookup is not designated


def test_an_answer_for_another_name_approves_nothing(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80"), "no successful dns_lookup_for_fqdn answer for www.google.com",
            answers=[answer("www.cnn.com", "192.0.2.80")])


def test_the_names_case_does_not_matter(repo):
    write(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80"), [answer("WWW.Google.com", "192.0.2.80")])


def test_the_live_draft_passes_the_responses_answers_to_the_draft_check():
    """workflow.agent.dns_answers reads each dns_lookup_for_fqdn output from the response; refusals are left out."""
    import json
    from types import SimpleNamespace
    from workflow.agent import designated_addresses, dns_answers
    item = lambda name, out: SimpleNamespace(type="mcp_call", name=name, output=json.dumps(out))  # noqa: E731
    response = SimpleNamespace(output=[
        item("locate_address_for_env_site", {"input": "10.100.14.0/24"}),
        item("dns_lookup_for_fqdn", {"error": "not a valid hostname"}),
        item("dns_lookup_for_fqdn", answer("www.google.com", "192.0.2.80")),
        item("dns_lookup_for_fqdn", answer("www.google.com", "192.0.2.90")),
        SimpleNamespace(type="message", name="", output="")])
    found = dns_answers(response)
    assert [a["a"] for a in found] == [["192.0.2.80"], ["192.0.2.90"]]
    assert designated_addresses(found) == {"www.google.com": ["192.0.2.80"]}
