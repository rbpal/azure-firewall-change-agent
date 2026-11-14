"""URL destinations: the rule takes the URL's hostname and port; the URL, path and all, stays on the ticket.

RITM0011015 is the case: on 2026-10-25 the drafter (version 3) put the whole URL in the rule. A URL that states a port the ticket's protocol or ports do not give goes back to the engineer.
Each check here must be able to fail.
"""

import copy
import json

import pytest

import workflow.cli as cli
from evals.least_privilege import score_least_privilege as score
from workflow.agent import instructions
from workflow.scope import ApprovalError, plan_writes
from workflow.urls import CODE, NON_HTTP, url_conflicts, url_host, url_port
from tests.workflow.test_cli import REPO, changed, repo, request, run, snapshot  # noqa: F401  (repo is a fixture)

NUMBER = "RITM0011015"
LAB = {"infra/envs/lab-eastus2/firewall_policy_rule_collection_groups/xfer.tfvars",
       "infra/envs/lab-centralus/firewall_policy_rule_collection_groups/xfer.tfvars"}


def v3_reply(number):
    """The version 3 drafter's reply on 2026-10-25: the labelled rules with the whole URL as destination."""
    ticket, label = request(number)
    reply = {"outcome": "draft", "rules": copy.deepcopy(label["rules"])}
    for rule in reply["rules"]:
        rule["destinations"] = [ticket["destination"][0]["url"]]
    return reply


def with_url(url, protocol="HTTPS", ports=("443",)):
    """RITM0011015's ticket with another URL, protocol and ports."""
    t = copy.deepcopy(request(NUMBER)[0])
    t.update(destination=[{"url": url}], protocol=protocol, ports=list(ports))
    return t


# The written rule: the agent reads it in its instructions, matching the ticket schema.

def test_the_instructions_say_a_url_gives_its_hostname_and_port_and_the_path_stays_on_the_ticket():
    text = instructions(REPO)
    schema = json.loads((REPO / "data" / "tickets" / "schema.json").read_text())
    assert "The rule uses its hostname and port; the path stays on the ticket" in json.dumps(schema)
    assert "- A URL approves its hostname and port, on a destination only." in text  # STD-COLL-03
    assert "the rule does not restrict the path" in text
    assert "Never correct, replace or guess a hostname" in text  # drafter.md
    assert "`url_port_conflict`" in text  # RB-01-6
    assert "including a URL on a TCP, UDP, ICMP or Any ticket: `non_http_to_hostname`" in text  # RB-01-6
    assert "A URL on a TCP, UDP, ICMP or Any ticket is non-HTTP traffic to a hostname (`non_http_to_hostname`" in text
    assert "as the ticket gives them, except a URL" in text  # drafter.md, the rule's fields


# Python: the hostname exactly as the URL writes it; a stated port must agree with the ticket.

@pytest.mark.parametrize("url, host, port", [
    ("https://api.litware.example/v1/upload", "api.litware.example", None),
    ("https://API.Litware.example:8443/v1/upload?x=1", "api.litware.example", 8443),
    ("http://api.litware.example:80", "api.litware.example", 80),
])
def test_a_url_gives_its_own_hostname_and_any_port_it_states(url, host, port):
    assert url_host(url) == host and url_port(url) == port


@pytest.mark.parametrize("url, protocol, ports, conflict", [
    ("https://api.litware.example/v1/upload", "HTTPS", ["443"], False),     # no port stated: the ticket's port
    ("https://api.litware.example:443/v1/upload", "HTTPS", ["443"], False),
    ("https://api.litware.example:8443/v1/upload", "HTTPS", ["8443"], False),
    ("https://api.litware.example:8443/v1/upload", "HTTPS", ["443"], True),   # URL 8443, ticket 443
    ("https://api.litware.example:8443/v1/upload", "HTTPS", ["443", "8443"], True),  # one port, never picked
    ("http://api.litware.example:8080/", "HTTPS", ["8080"], True),             # scheme HTTP, ticket HTTPS
    ("http://api.litware.example/v1/upload", "HTTPS", ["443"], True),         # no port stated, scheme still checked
    ("http://api.litware.example/v1/upload", "HTTP", ["80"], False),
])
def test_a_stated_url_port_must_agree_with_the_tickets_protocol_and_ports(url, protocol, ports, conflict):
    found = url_conflicts(with_url(url, protocol, ports))
    assert bool(found) == conflict
    if conflict:
        assert found[0]["where"] == "destination/0/url" and "will not pick them" in found[0]["message"]


SCHEMA = json.loads((REPO / "data" / "tickets" / "schema.json").read_text())
PROTOCOLS = SCHEMA["properties"]["protocol"]["enum"]  # TCP, UDP, ICMP, Any, HTTP, HTTPS
URL_PATTERN = SCHEMA["$defs"]["address"]["properties"]["url"]["pattern"]


def test_the_schema_allows_only_http_and_https_urls():
    import re
    assert re.match(URL_PATTERN, "http://api.litware.example/v1") and re.match(URL_PATTERN, "https://api.litware.example")
    assert not re.match(URL_PATTERN, "ftp://api.litware.example/file")
    assert {"HTTP", "HTTPS"} <= set(PROTOCOLS)


@pytest.mark.parametrize("scheme", ["http", "https"])
@pytest.mark.parametrize("protocol", PROTOCOLS)
@pytest.mark.parametrize("stated", [None, "same", "other"])
def test_every_schema_scheme_and_protocol_combination(scheme, protocol, stated):
    # HTTP or HTTPS ticket: the scheme is the protocol and a stated port is the ticket's one port, else
    # url_port_conflict. TCP, UDP, ICMP or Any ticket: a URL is non-HTTP traffic to a hostname, whatever its port.
    port = {None: "", "same": ":8443", "other": ":9443"}[stated]
    found = url_conflicts(with_url(f"{scheme}://api.litware.example{port}/v1/upload", protocol, ["8443"]))
    if protocol not in ("HTTP", "HTTPS"):
        assert [f["code"] for f in found] == [NON_HTTP], (scheme, protocol, stated)
        assert f"the ticket's protocol is {protocol}" in found[0]["message"]
        return
    assert bool(found) == (protocol != scheme.upper() or stated == "other"), (scheme, protocol, stated)
    if found:
        text = found[0]["message"]
        assert found[0]["code"] == CODE
        assert ("its scheme is" in text) == (protocol != scheme.upper())
        assert ("it states port 9443" in text) == (stated == "other")


def test_a_url_on_a_tcp_ticket_is_non_http_to_hostname_at_intake_and_never_reaches_the_agent(repo, tmp_path,
                                                                                               monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "read_reply", lambda path: calls.append(path) or {"outcome": "draft", "rules": []})
    ticket = tmp_path / "t.json"
    ticket.write_text(json.dumps(with_url("https://api.litware.example/v1/upload", "TCP", ["443"])))
    before = snapshot(repo)
    assert run(repo, "submit", str(ticket)) == cli.REVIEW
    out = capsys.readouterr().out
    assert f"[{NON_HTTP}, needs an edit] destination/0/url" in out and CODE not in out
    version = cli.load_record(repo, NUMBER)["ticket_version"][:12]
    assert run(repo, "accept", NUMBER, "--ticket-version", version, "--engineer", "E", "--reason", "r",
               "--reply", "unused.json") == cli.REFUSED
    assert calls == [] and changed(before, repo) == set()


def test_a_draft_write_refuses_a_url_on_a_tcp_ticket_as_non_http_to_hostname(repo):
    reply = copy.deepcopy(request(NUMBER)[1])
    with pytest.raises(ApprovalError, match=NON_HTTP):
        plan_writes(repo, with_url("https://api.litware.example/v1/upload", "TCP", ["443"]), reply)


def test_no_validation_or_sample_ticket_has_a_url_port_conflict():
    for path in sorted((REPO / "evals" / "requests" / "validation").glob("*.yaml")):
        import yaml
        assert url_conflicts(yaml.safe_load(path.read_text())["ticket"]) == [], path.name


def test_a_url_port_conflict_waits_for_an_edit_and_never_reaches_the_agent(repo, tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "read_reply", lambda path: calls.append(path) or {"outcome": "draft", "rules": []})
    ticket = tmp_path / "t.json"
    ticket.write_text(json.dumps(with_url("https://api.litware.example:8443/v1/upload")))
    before = snapshot(repo)
    assert run(repo, "submit", str(ticket)) == cli.REVIEW
    assert f"[{CODE}, needs an edit] destination/0/url" in capsys.readouterr().out
    version = cli.load_record(repo, NUMBER)["ticket_version"][:12]
    assert run(repo, "accept", NUMBER, "--ticket-version", version, "--engineer", "E", "--reason", "r",
               "--reply", "unused.json") == cli.REFUSED
    assert calls == [] and changed(before, repo) == set()


def test_a_draft_write_refuses_a_ticket_with_a_url_port_conflict(repo):
    reply = copy.deepcopy(request(NUMBER)[1])
    with pytest.raises(ApprovalError, match=CODE):
        plan_writes(repo, with_url("https://api.litware.example:8443/v1/upload"), reply)


@pytest.mark.parametrize("number", ["RITM0011015"])
def test_the_version_3_replies_with_the_whole_url_are_refused_and_the_labelled_hostname_writes(repo, number):
    with pytest.raises(ApprovalError, match="is not on the ticket"):
        plan_writes(repo, request(number)[0], v3_reply(number))
    assert len(plan_writes(repo, *request(number))) == 2


def test_a_corrected_or_substituted_hostname_is_refused(repo):
    reply = copy.deepcopy(request(NUMBER)[1])
    for rule in reply["rules"]:
        rule["destinations"] = ["api.litware.example.com"]  # a "fixed" name the URL does not give
    with pytest.raises(ApprovalError, match="is not on the ticket"):
        plan_writes(repo, request(NUMBER)[0], reply)


# The scorer: the same comparison with the label, and a message that says what it compared.

@pytest.mark.parametrize("number", ["RITM0011015"])
def test_the_scorer_still_fails_the_whole_url_and_now_names_the_labelled_hostname(number):
    label = request(number)[1]
    result = score(label, v3_reply(number))
    assert result.result == "fail"
    host = label["rules"][0]["destinations"][0]
    assert all(f"the labelled rule approves {host}" in line for line in result.excess)
    assert all("a rule takes a URL's hostname, not the URL" in line for line in result.excess)
    assert score(label, {"outcome": "draft", "rules": copy.deepcopy(label["rules"])}).result == "pass"
