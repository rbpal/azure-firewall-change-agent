"""The required-tool scorer, on real labelled tickets. Every check here must be able to fail."""

from evals.required_tools import DNAT_PORT, DNS, DUPLICATE, LOCATE, missing_tools
from evals.run_eval import load_requests, run, summarise
from workflow.agent import Call

REQUESTS = {r.number: r for r in load_requests("validation")}


def call(name, **arguments):
    """One recorded tool call."""
    return {"name": name, "arguments": arguments}


def missing(number, *tool_calls):
    """What the scorer says this labelled ticket skipped, given these calls."""
    request = REQUESTS[number]
    return missing_tools(request.ticket, request.expected, list(tool_calls))


def test_an_open_source_must_be_looked_up_even_when_the_label_lists_no_tools():
    ticket = REQUESTS["RITM0011059"].ticket
    destination = call(LOCATE, address="10.102.20.14/32")
    assert missing_tools(ticket, {"tools": []}, [destination]) == [f"{LOCATE} 0.0.0.0/0"]
    assert missing_tools(ticket, {"tools": []}, [destination, call(LOCATE, address="0.0.0.0/0")]) == []


def test_a_non_http_hostname_stop_needs_its_dns_lookup():
    sources = [call(LOCATE, address="10.102.15.0/24"), call(LOCATE, address="10.103.15.0/24")]
    assert missing("RITM0011064", *sources) == [DNS]
    assert missing("RITM0011064", *sources, call(DNS, target="api.tailspin.example")) == []


def test_star_is_exempt_because_the_tool_refuses_it():
    ticket = {"item": "Firewall Change Request", "sources": [{"cidr": "*"}], "destination": [{"cidr": "10.102.20.14/32"}]}
    assert missing_tools(ticket, {"tools": []}, [call(LOCATE, address="10.102.20.14/32")]) == []


def test_an_ip_group_source_must_be_looked_up_by_name():
    ticket = {"item": "Firewall Change Request", "sources": [{"ip_group": "ipg-ledg-prod-dr"}], "destination": []}
    assert missing_tools(ticket, {"tools": []}, []) == [f"{LOCATE} ipg-ledg-prod-dr"]
    assert missing_tools(ticket, {"tools": []}, [call(LOCATE, address="ipg-ledg-prod-dr")]) == []


def test_a_host_written_with_or_without_its_prefix_is_the_same_lookup():
    ticket = {"item": "Firewall Change Request", "sources": [{"cidr": "10.102.20.14/32"}], "destination": []}
    assert missing_tools(ticket, {"tools": []}, [call(LOCATE, address="10.102.20.14")]) == []
    assert missing_tools(ticket, {"tools": []}, [call(LOCATE, address="10.102.20.15")]) != []


def test_a_removal_needs_its_duplicate_check_at_the_labelled_site_and_no_lookup():
    assert missing("RITM0011050") == [f"{DUPLICATE} prod-centralus"]
    assert missing("RITM0011050", call(DUPLICATE, env_site="prod-eastus2")) == [f"{DUPLICATE} prod-centralus"]
    assert missing("RITM0011050", call(DUPLICATE, env_site="prod-centralus")) == []


def test_a_dnat_draft_needs_its_port_check_at_every_site():
    request = REQUESTS["RITM0011020"]
    sites = [r["env_site"] for r in request.expected["rules"]]
    made = [call(LOCATE, address=e["cidr"]) for e in request.ticket["sources"] + request.ticket["destination"]]
    made += [call(DUPLICATE, env_site=site) for site in sites]
    assert missing_tools(request.ticket, request.expected, made) == [f"{DNAT_PORT} {site}" for site in sites]
    assert missing_tools(request.ticket, request.expected, made + [call(DNAT_PORT, env_site=s) for s in sites]) == []


def test_a_labelled_dns_lookup_is_required():
    request = REQUESTS["RITM0011063"]
    made = [call(LOCATE, address=e["cidr"]) for e in request.ticket["sources"] + request.ticket["destination"] if "cidr" in e]
    assert missing_tools(request.ticket, request.expected, made) == [DNS]
    assert missing_tools(request.ticket, request.expected, made + [call(DNS, target="x")]) == []


class Recording:
    """An agent that gives the labelled answer and records the tool calls it is told to."""

    def __init__(self, tool_calls):
        """Keep the calls each answer claims to have made."""
        self.tool_calls, self.calls = tool_calls, []

    def __call__(self, ticket, engineer_review=None, dns_lookup=None):
        """Answer one ticket with its label, and record one call."""
        self.calls.append(Call(ticket["number"], tool_calls=list(self.tool_calls)))
        expected = REQUESTS[ticket["number"]].expected
        return {key: expected[key] for key in ("outcome", "reason", "action", "rules") if key in expected}


def test_a_right_answer_that_skipped_a_lookup_fails_the_ticket_and_is_counted():
    results = run(Recording([call(LOCATE, address="10.102.20.14/32")]), only={"RITM0011059"})
    assert results[0].verdict.mistakes == ["skipped_tool"] and not results[0].verdict.passed
    assert results[0].verdict.detail == [f"skipped {LOCATE} 0.0.0.0/0"]
    assert summarise(results)["mistakes"]["skipped_tool"] == 1


def test_a_right_answer_with_every_required_call_passes():
    made = [call(LOCATE, address="10.102.20.14/32"), call(LOCATE, address="0.0.0.0/0")]
    assert run(Recording(made), only={"RITM0011059"})[0].verdict.complete
