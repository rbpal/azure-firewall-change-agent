"""An invalid agent reply is kept for diagnosis: its raw text and response ID, in the eval output and the workflow record.

RITM0011050 is the case: on 2026-10-25 the drafter (version 3) stopped without the reason the reply
format requires. The runner kept only the error, so the reply had to be read back from the trace.
Each check here must be able to fail.
"""

import json

import pytest

import workflow.cli as cli
from evals.run_eval import run as run_eval
from workflow.agent import RAW_LIMIT, AgentError, parse_reply
from tests.workflow.test_agent import foundry
from tests.workflow.test_cli import changed, repo, request, run, snapshot  # noqa: F401  (repo is a fixture)

NUMBER = "RITM0011050"
# The version 3 drafter's text for RITM0011050, trace fbff63cff9022f81484a5e13c15442cb.
V3_TEXT = ('{"outcome":"stop_and_ask","rules":[],"explanation":"The ticket selects prod DR, but the address lookup '
           'tool does not accept `prod-dr` and the available data does not identify which canonical prod env-site is '
           'DR. Please clarify the env-site to check before any rules are removed."}')


def test_parse_reply_keeps_the_raw_text_of_an_invalid_reply():
    with pytest.raises(AgentError, match="'reason' is a required property") as raised:
        parse_reply(V3_TEXT)
    assert raised.value.raw == V3_TEXT
    with pytest.raises(AgentError) as raised:
        parse_reply("x" * (RAW_LIMIT + 50))  # not JSON, and longer than is kept
    assert raised.value.raw == "x" * RAW_LIMIT


def test_a_valid_reply_carries_no_raw_text_and_an_infrastructure_error_none_either():
    assert parse_reply('{"outcome": "stop_and_ask", "reason": "hub_rule", "rules": []}')["reason"] == "hub_rule"
    with pytest.raises(AgentError) as raised:
        foundry("", fail=TimeoutError("no answer"))({"number": NUMBER})
    assert raised.value.raw is None


def test_the_call_record_keeps_the_raw_reply_and_the_response_id():
    agent = foundry(V3_TEXT, id="resp_038cdb237cf8f3ea006ade4c5f982c8195bf9452393f83cf6a")
    with pytest.raises(AgentError):
        agent({"number": NUMBER})
    call = agent.calls[0]
    assert call.raw_reply == V3_TEXT and call.response_id == "resp_038cdb237cf8f3ea006ade4c5f982c8195bf9452393f83cf6a"
    assert call.error.startswith("the agent's reply does not fit")


def test_the_eval_output_keeps_the_raw_reply_of_an_agent_error():
    def v3(ticket, engineer_review=None, **_):
        """The version 3 drafter: an invalid reply for RITM0011050."""
        return parse_reply(V3_TEXT)

    replies = []
    results = [r for r in run_eval(v3, only={NUMBER}, replies=replies) if r.number == NUMBER]
    assert results[0].verdict.mistakes == ["agent_error"]
    entry = next(r for r in replies if r["number"] == NUMBER)
    assert entry["reply"] is None and entry["raw_reply"] == V3_TEXT


def test_the_workflow_record_keeps_the_raw_reply_and_nothing_else_changes(repo, tmp_path, monkeypatch, capsys, offline_main):
    monkeypatch.setenv("FWAGENT_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")
    monkeypatch.setattr(cli, "live_agent", lambda *_: lambda ticket, engineer_review=None: parse_reply(V3_TEXT))
    ticket = tmp_path / "t.json"
    ticket.write_text(json.dumps(request(NUMBER)[0]))
    assert run(repo, "submit", str(ticket)) == cli.REVIEW
    version = cli.load_record(repo, NUMBER)["ticket_version"]
    before = snapshot(repo)
    assert run(repo, "accept", NUMBER, "--ticket-version", version[:12], "--engineer", "Jordan Patel",
               "--reason", "checked") == cli.REFUSED
    assert "'reason' is a required property" in capsys.readouterr().out
    record = cli.load_record(repo, NUMBER)
    kept = record["history"][-1]
    assert (kept["action"], kept["raw_reply"], kept["ticket_version"]) == ("draft_stopped", V3_TEXT, version)
    # the acceptance of this exact, unchanged ticket is kept, so fwagent draft can try again without a new accept
    assert record["status"] == "accepted" and record["reply"] is None and record["review"]["ticket_version"] == version
    assert changed(before, repo) == set()


# The action field: only on a removal draft. Version 4 added it to two stops on 2026-10-25 (RITM0011061, RITM0011065).

@pytest.mark.parametrize("reply", [
    {"outcome": "stop_and_ask", "reason": "both_ends_onprem", "action": "remove", "rules": []},
    {"outcome": "stop_and_ask", "reason": "rule_allows_more", "action": "remove", "rules": []},
    {"outcome": "already_allowed", "action": "remove", "rules": [{"env_site": "prod-eastus2", "spoke": "sett",
     "collection": "allow-sett-network-rules", "name": "x", "sources": ["10.100.14.0/24"],
     "destinations": ["203.0.113.48/28"], "ports": ["22"], "protocol": "TCP"}]},
])
def test_the_validator_stays_strict_action_on_a_stop_or_already_allowed_is_refused(reply):
    with pytest.raises(AgentError, match="False schema does not allow 'remove'") as raised:
        parse_reply(json.dumps(reply))
    assert raised.value.raw == json.dumps(reply)


def test_the_instructions_say_action_only_on_a_removal_draft():
    from workflow.agent import instructions
    from tests.workflow.test_cli import REPO
    text = instructions(REPO)
    assert "- `action`: `\"remove\"` only when `outcome` is `draft` and the ticket removes rules." in text
    assert "always omit it for `stop_and_ask` and `already_allowed`, even on a removal ticket" in text
