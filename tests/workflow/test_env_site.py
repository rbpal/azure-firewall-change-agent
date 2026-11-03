"""Env-site without an address: the agent resolves prod DR to prod-centralus with a tool, or stops for the engineer.

RITM0011050 is the case: prod DR only, an IP-group source and a partner destination, so the
address lookup gives no env-site. On 2026-10-25 the drafter (version 3) made up "prod-dr" and
stopped without a reason. Each check here must be able to fail.
"""

import ast
import copy
import json
from pathlib import Path

import pytest

import workflow.cli as cli
from workflow.agent import READS_MAIN, TOOLS, definition, instructions
from tests.workflow.test_cli import REPO, changed, repo, request, run, snapshot  # noqa: F401  (repo is a fixture)

NUMBER = "RITM0011050"
PROD_DR = "infra/envs/prod-centralus/firewall_policy_rule_collection_groups/ledg.tfvars"
UNRESOLVED = {"outcome": "stop_and_ask", "reason": "env_site_not_found", "rules": [],
              "explanation": "routing.yaml lists no env-site for environment prod and site dr. Which env-site is meant?"}


def submit_and_accept(repo, tmp_path, reply):
    """Submit RITM0011050, accept its exact version with `reply` as the agent's answer; return the exit code."""
    ticket = tmp_path / "t.json"
    ticket.write_text(json.dumps(request(NUMBER)[0]))
    assert run(repo, "submit", str(ticket)) == cli.REVIEW
    reply_file = tmp_path / "r.json"
    reply_file.write_text(json.dumps(reply))
    version = cli.load_record(repo, NUMBER)["ticket_version"][:12]
    return run(repo, "accept", NUMBER, "--ticket-version", version, "--engineer", "Jordan Patel", "--reason", "checked",
               "--reply", str(reply_file))


# The agent gets the tool and the instructions, in production and in the evaluation alike:
# both call the one FoundryAgent, whose definition is built here.

def registered_tools():
    """Tool names registered in mcp/function_app.py."""
    tree = ast.parse((REPO / "mcp" / "function_app.py").read_text())
    return {k.value.value for node in tree.body if isinstance(node, ast.FunctionDef) for d in node.decorator_list
            if isinstance(d, ast.Call) for k in d.keywords if k.arg == "tool_name"}


def test_the_agent_may_call_resolve_env_site_and_every_allowed_tool_is_registered():
    body = definition(instructions(REPO))
    assert "resolve_env_site" in body["tools"][0]["allowed_tools"]
    assert set(TOOLS) <= registered_tools()


def test_the_env_site_answer_must_come_from_the_pinned_snapshot():
    assert "resolve_env_site" in READS_MAIN


def test_the_instructions_say_when_to_use_the_tool_and_how_to_stop_when_it_cannot_resolve():
    text = instructions(REPO)
    assert "`resolve_env_site`: the env-site name" in text
    assert "If `resolve_env_site` answers `resolved: false`, stop with reason `env_site_not_found`" in text
    assert "never read one from an IP group's name" in text


def test_the_instructions_say_every_stop_carries_a_reason_even_when_no_listed_code_fits():
    # The reply format requires it; version 3 left it out on RITM0011050.
    text = instructions(REPO)
    assert "- `reason`: for `stop_and_ask`, always:" in text
    assert "If you must stop and no listed code fits, use `needs_engineer_review`" in text
    assert "*no code yet*" not in text


# The workflow: a resolved site drafts there only; an unresolved one goes back to the engineer.

def test_the_labelled_removal_at_prod_centralus_writes_only_the_prod_dr_file(repo, tmp_path):
    before = snapshot(repo)
    assert submit_and_accept(repo, tmp_path, request(NUMBER)[1]) == cli.DONE
    assert changed(before, repo) == {PROD_DR}


def test_an_unresolved_site_returns_the_ticket_to_the_engineer_with_its_reason(repo, tmp_path, capsys):
    before = snapshot(repo)
    assert submit_and_accept(repo, tmp_path, UNRESOLVED) == cli.REVIEW
    out = capsys.readouterr().out
    assert "[env_site_not_found, needs an edit] (agent)" in out and "Which env-site is meant?" in out
    record = cli.load_record(repo, NUMBER)
    assert record["status"] == "awaiting_review" and record["status"] != "rejected"
    assert record["keys"] == [] and record["files"] == {}
    assert changed(before, repo) == set()


def test_a_stop_without_its_reason_is_still_refused_and_writes_nothing(repo, tmp_path, monkeypatch, capsys):
    # The reply format requires the reason on every stop; the drafter left it out on 2026-10-25.
    from workflow.agent import AgentError, parse_reply
    reply = {k: v for k, v in UNRESOLVED.items() if k != "reason"}
    with pytest.raises(AgentError, match="'reason' is a required property"):
        parse_reply(json.dumps(reply))


@pytest.mark.parametrize("site", ["prod-dr", "prod-eastus2"])
def test_a_draft_at_a_guessed_or_wrong_site_is_refused_and_writes_nothing(repo, tmp_path, capsys, site):
    reply = copy.deepcopy(request(NUMBER)[1])
    reply["rules"][0]["env_site"] = site
    before = snapshot(repo)
    assert submit_and_accept(repo, tmp_path, reply) == cli.REFUSED
    assert "does not select" in capsys.readouterr().out
    assert changed(before, repo) == set() and cli.load_record(repo, NUMBER)["status"] == "awaiting_review"
