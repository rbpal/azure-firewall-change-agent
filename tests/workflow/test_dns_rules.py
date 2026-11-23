"""Exact FQDNs drafted as network rules that name the FQDN, and the scope checks its DNS answer passes.

The ticket is the prod primary-only sett ticket from test_scope.py (source 10.100.14.0/24 at prod-eastus2), given an
FQDN destination. The reply is what the agent drafts after dns_lookup_for_fqdn answered: a network rule to the FQDN.
The answer's addresses come from the synthetic plan: 192.0.2.x is public (documentation range, outside the plan).
Every check here must be able to fail.
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


def _name(ticket):
    """The name the rule and the lookup use: the ticket's FQDN, a URL's host included, without a leading www."""
    given = ticket["destination"][0]
    name = given.get("fqdn") or given["url"].split("/")[2]
    return name[4:] if name.startswith("www.") else name


def resolving(ticket, *addresses):
    """The response's one DNS answer: the ticket's FQDN resolving to these addresses."""
    return [answer(_name(ticket), *addresses)]


def write(repo, ticket, reply, answers=None):
    """apply_reply with the response's DNS answers: by default, the ticket's FQDN resolving to 192.0.2.80."""
    return apply_reply(repo, ticket, reply, dns_answers=resolving(ticket, "192.0.2.80") if answers is None else answers)


def drafted(*destinations, protocol="TCP", ports=("443",)):
    """The agent's primary-site draft to these destinations (by default google.com, the ticket's www.google.com without www.)."""
    r = flow_reply(protocol, ports)
    r["rules"][0]["destinations"] = list(destinations or ["google.com"])
    return r


def refused(repo, ticket, reply, why, answers=None):
    """Assert the draft is refused for `why` and writes nothing."""
    before = snapshot(repo)
    with pytest.raises(ApprovalError, match=why):
        write(repo, ticket, reply, answers)
    assert changed(before, repo) == set()


def test_an_exact_fqdn_becomes_a_tcp_443_network_rule_naming_the_fqdn(repo):
    before = snapshot(repo)
    write(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(), resolving(flow_ticket("HTTPS", ["443"], FQDN), "192.0.2.80", "192.0.2.81"))
    assert changed(before, repo) == {SPOKE_FILE.format(PRIMARY)}
    text = (repo / SPOKE_FILE.format(PRIMARY)).read_text()
    assert "destination_fqdns" in text and '"google.com"' in text and "www." not in text and "192.0.2.8" not in text


def test_a_www_fqdn_in_a_network_rule_is_refused(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("www.google.com"), "starts with www.",
            answers=[answer("www.google.com", "192.0.2.80")])


def test_a_url_destination_is_handled_like_its_fqdn(repo):
    before = snapshot(repo)
    write(repo, flow_ticket("HTTPS", ["443"], {"url": "https://www.google.com/"}), drafted())
    assert changed(before, repo) == {SPOKE_FILE.format(PRIMARY)}


@pytest.mark.parametrize("protocol, ports", [("UDP", ["53"]), ("TCP", ["5671"]), ("HTTP", ["80"])])
def test_the_tickets_transport_and_ports_are_kept_and_http_becomes_tcp(repo, protocol, ports):
    rule_protocol = "TCP" if protocol == "HTTP" else protocol
    write(repo, flow_ticket(protocol, ports, FQDN), drafted(protocol=rule_protocol, ports=ports))


def test_https_kept_as_https_to_an_exact_fqdn_is_refused(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(protocol="HTTPS"),
            "HTTP and HTTPS to them become a TCP network rule")


def test_a_wider_port_than_the_ticket_is_still_refused(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(ports=["443", "8443"]), "port 8443 is not within")


def test_the_fqdns_resolved_addresses_are_refused_in_the_rule(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("192.0.2.80"),
            "192.0.2.80 is a CIDR, a type the ticket does not approve here")


def test_an_fqdn_the_ticket_does_not_give_is_refused(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted("www.cnn.com"), "www.cnn.com is not on the ticket",
            answers=[answer("www.cnn.com", "192.0.2.80")])


def test_a_wildcard_domain_pattern_is_never_a_network_rule(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], {"fqdn": "*.google.com"}), drafted("*.google.com"),
            "non_http_to_hostname", answers=[])


@pytest.mark.parametrize("address", ["0.0.0.1", "127.0.0.1", "169.254.10.10", "224.0.0.5", "240.0.0.1", "255.255.255.255"])
def test_a_never_allowed_answer_stops_as_dns_lookup_failed(repo, address):
    t = flow_ticket("HTTPS", ["443"], FQDN)
    refused(repo, t, drafted(), f"{address} is a .*dns_lookup_failed", resolving(t, address))


def test_an_internal_answer_at_the_rules_own_env_site_is_allowed(repo):
    """Private is not refused for being private: 10.100.15.10 is prod-eastus2's rprt spoke, the rule's own env-site."""
    t, before = flow_ticket("HTTPS", ["443"], INTERNAL), snapshot(repo)
    write(repo, t, drafted("reports.internal.example"), resolving(t, "10.100.15.10"))
    assert changed(before, repo) == {SPOKE_FILE.format(PRIMARY)}


def test_an_onprem_answer_is_allowed(repo):
    t = flow_ticket("HTTPS", ["443"], ONPREM)
    write(repo, t, drafted("erp.corp.example"), resolving(t, "172.20.10.5"))


def test_an_answer_at_the_other_site_returns_the_ticket_naming_the_missing_routing_fact(repo):
    """10.101.15.10 is prod-centralus. routing.yaml records no path between hubs, so the firewalls are not established."""
    t = flow_ticket("HTTPS", ["443"], INTERNAL)
    refused(repo, t, drafted("reports.internal.example"),
            r"10.101.15.10 sits at prod-centralus.*records no path between hubs.*afw-hub-prod-centralus.*"
            "needs_engineer_review", resolving(t, "10.101.15.10"))


def test_an_answer_in_another_environment_is_env_mismatch(repo):
    t = flow_ticket("HTTPS", ["443"], INTERNAL)
    refused(repo, t, drafted("reports.internal.example"),
            "10.102.15.10 sits in stage-eastus2, environment stage, not the ticket's prod.*env_mismatch",
            resolving(t, "10.102.15.10"))


@pytest.mark.parametrize("address", ["192.168.50.5", "100.64.1.1"], ids=["private", "shared"])
def test_a_private_or_shared_answer_outside_the_plan_is_address_not_in_plan(repo, address):
    t = flow_ticket("HTTPS", ["443"], FQDN)
    refused(repo, t, drafted(), f"{address} is a private or shared.*address_not_in_plan", resolving(t, address))


def test_an_answer_no_spoke_owns_is_planned_address(repo):
    t = flow_ticket("HTTPS", ["443"], FQDN)
    refused(repo, t, drafted(), "10.100.200.5 is inside prod-eastus2.*planned_address", resolving(t, "10.100.200.5"))


def test_a_source_whose_spoke_has_no_internet_next_hop_is_not_on_the_path(repo):
    """With sett's internet route removed from routing.yaml, the rule's firewall is not on the source's path."""
    path = repo / "data" / "network" / "routing.yaml"
    data = yaml.safe_load(path.read_text())
    data["env_sites"][PRIMARY]["spokes"]["sett"]["for"] = ["private"]
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(),
            "does not reach afw-hub-prod-eastus2 as routing.yaml's internet next hop")
    t = flow_ticket("HTTPS", ["443"], INTERNAL)
    write(repo, t, drafted("reports.internal.example"), resolving(t, "10.100.15.10"))  # private still is


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

def test_with_no_dns_answer_in_the_response_the_fqdn_is_refused(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(),
            "no successful dns_lookup_for_fqdn answer for google.com in this draft's response", answers=[])


def test_a_failed_lookup_is_refused(repo):
    """NXDOMAIN, or a name with no A record, is not a successful answer, so the FQDN rule is refused."""
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(), "no successful dns_lookup_for_fqdn answer",
            answers=[answer("google.com", resolves=False)])
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(), "no successful dns_lookup_for_fqdn answer",
            answers=[{"host": "google.com", "resolves": True, "a": [], "aaaa": ["2001:db8::1"]}])


def test_only_the_first_successful_answer_is_checked(repo):
    good, bad = answer("google.com", "192.0.2.80"), answer("google.com", "127.0.0.1")
    assert plan_writes(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(), dns_answers=[good, bad])
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(), "127.0.0.1 is a", [bad, good])
    assert plan_writes(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(),
                       dns_answers=[answer("google.com", resolves=False), good])  # a failed lookup is not designated


def test_an_answer_for_another_name_approves_nothing(repo):
    refused(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(), "no successful dns_lookup_for_fqdn answer for google.com",
            answers=[answer("www.cnn.com", "192.0.2.80")])


def test_the_names_case_does_not_matter(repo):
    write(repo, flow_ticket("HTTPS", ["443"], FQDN), drafted(), [answer("Google.COM", "192.0.2.80")])


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
