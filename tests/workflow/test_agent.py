"""The drafter on Foundry, tested offline with fake clients. No test here reaches Azure. Every check must be able to fail."""

import copy
import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import workflow.agent as agent_mod
import workflow.cli as cli
from workflow.agent import (AGENT_NAME, AgentError, FoundryAgent, data_differences, definition, ensure_version, instructions,
                            message, parse_reply)

REPO = Path(__file__).resolve().parents[2]
REQUESTS = REPO / "evals" / "requests"
LABELS = sorted(REQUESTS.glob("*/*.yaml"))
SNAP = "c" * 40  # the snapshot commit a run pins


def _reply_keys(expected):
    """The parts of a label a reply carries."""
    return {k: copy.deepcopy(expected[k]) for k in ("outcome", "reason", "action", "rules") if k in expected}


# ------------------------------------------------------------ the instructions

def test_instructions_hold_the_header_and_every_standard_and_runbook():
    text = instructions(REPO)
    assert text.startswith("# Firewall rule drafter")
    pages = sorted((REPO / "data" / "standards").glob("*.md")) + sorted((REPO / "data" / "runbooks").glob("*.md"))
    assert len(pages) == 7
    for page in pages:
        assert page.read_text().strip() in text, page.name


def test_nothing_the_agent_sees_names_a_test_ticket_or_holds_label_text():
    """The planned prompt check: instructions and every message carry no test-split number and no answer key."""
    tests = [yaml.safe_load(p.read_text()) for p in sorted((REQUESTS / "test").glob("*.yaml"))]
    numbers = {t["id"] for t in tests}
    notes = {t["expected"]["note"].strip() for t in tests if t["expected"].get("note")}
    seen = instructions(REPO)
    assert not any(n in seen for n in numbers)
    assert not any(note[:60] in seen for note in notes)
    for path in sorted((REQUESTS / "validation").glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        sent = json.loads(message(data["ticket"], data.get("engineer_review")))
        assert set(sent) == {"ticket", "engineer_review"}
        assert "expected" not in json.dumps(sent) and data["expected"].get("note", "")[:60] not in json.dumps(sent)


# ------------------------------------------------------------ the agent definition

def test_the_definition_gives_three_read_tools_over_the_project_connection_with_no_approval_step():
    body = definition("x", SNAP, "gpt-6-luna-agent", "mcp-fwagentic-tools")
    tool = body["tools"][0]
    assert body["model"] == "gpt-6-luna-agent" and len(body["tools"]) == 1
    assert tool["type"] == "mcp" and tool["project_connection_id"] == "mcp-fwagentic-tools"
    assert tool["server_url"] == "https://func-fwagentic-dev.azurewebsites.net/runtime/webhooks/mcp"
    assert sorted(tool["allowed_tools"]) == ["dns_lookup_for_fqdn", "duplicate_rule_check", "locate_address_for_env_site"]
    assert tool["require_approval"] == "never"
    assert tool["headers"] == {"X-Fwagent-Snapshot": SNAP}  # every tool call of the ticket reads this commit


@pytest.mark.parametrize("snapshot", ["", "main", "c" * 39, "C" * 40, "c" * 40 + "\n"])
def test_the_definition_needs_a_full_snapshot_sha(snapshot):
    with pytest.raises(AgentError, match="full commit SHA"):
        definition("x", snapshot)


def test_another_snapshot_makes_another_agent_version():
    assert agent_mod.definition_sha(definition("x", SNAP)) != agent_mod.definition_sha(definition("x", "d" * 40))


class FakeAgents:
    """Stands in for project.agents: lists versions and records each create_version."""

    def __init__(self, versions=(), missing=False):
        self.versions, self.missing, self.created = list(versions), missing, []

    def list_versions(self, name):
        if self.missing:
            raise type("ResourceNotFoundError", (Exception,), {"status_code": 404})("no agent")
        return self.versions

    def create_version(self, name, definition, metadata, description):
        self.created.append((name, definition, metadata))
        return SimpleNamespace(version=str(len(self.versions) + len(self.created)))


def test_an_unchanged_definition_reuses_its_version_and_a_changed_one_makes_a_new_version():
    body = definition("instructions v1", SNAP)
    sha = agent_mod.definition_sha(body)
    same = FakeAgents([SimpleNamespace(version="3", metadata={"definition_sha": sha})])
    assert ensure_version(SimpleNamespace(agents=same), body) == "3" and same.created == []
    other = FakeAgents([SimpleNamespace(version="3", metadata={"definition_sha": sha})])
    assert ensure_version(SimpleNamespace(agents=other), definition("instructions v2", SNAP)) == "2"
    name, made, metadata = other.created[0]
    assert name == AGENT_NAME and made.model == "gpt-6-luna-agent" and made.instructions == "instructions v2"
    assert made.tools[0].project_connection_id == "mcp-fwagentic-tools" and made.tools[0].require_approval == "never"
    assert made.tools[0].headers == {"X-Fwagent-Snapshot": SNAP}
    assert metadata["definition_sha"] != sha


def test_the_first_version_is_created_when_no_agent_exists():
    agents = FakeAgents(missing=True)
    assert ensure_version(SimpleNamespace(agents=agents), definition("x", SNAP)) == "1"


# ------------------------------------------------------------ the reply

@pytest.mark.parametrize("path", LABELS, ids=lambda p: p.name)
def test_every_labelled_answer_fits_the_reply_schema(path):
    """The schema must never refuse a correct answer."""
    expected = yaml.safe_load(path.read_text())["expected"]
    assert parse_reply(json.dumps(_reply_keys(expected))) == _reply_keys(expected)


def test_a_reply_in_a_code_fence_with_an_explanation_is_read():
    text = '```json\n{"outcome": "stop_and_ask", "reason": "hub_rule", "rules": [], "explanation": "The rule is in the hub group."}\n```'
    assert parse_reply(text)["reason"] == "hub_rule"


BAD_REPLIES = {
    "not JSON": ("Sure! Here is the rule.", "is not JSON"),
    "unknown outcome": ('{"outcome": "approve", "rules": []}', "outcome"),
    "stop without a reason": ('{"outcome": "stop_and_ask", "rules": []}', "'reason' is a required property"),
    "stop that drafts rules": ('{"outcome": "stop_and_ask", "reason": "hub_rule", "rules": [{"env_site": "dev-eastus2"}]}', "rules"),
    "draft with no rule": ('{"outcome": "draft", "rules": []}', "rules"),
    "extra top-level key": ('{"outcome": "stop_and_ask", "reason": "hub_rule", "rules": [], "approved": true}', "approved"),
    "rule with an unknown field": ('{"outcome": "draft", "rules": [{"env_site": "dev-eastus2", "spoke": "sett", '
                                   '"collection": "allow-sett-network-rules", "name": "x", "sources": ["10.104.14.0/24"], '
                                   '"destinations": ["198.51.100.48/28"], "ports": ["587"], "protocol": "TCP", "action": "Allow"}]}',
                                   "action"),
    "translated address without a port": ('{"outcome": "draft", "rules": [{"env_site": "dev-eastus2", "spoke": "xfer", '
                                          '"collection": "allow-xfer-dnat-rules", "name": "x", "sources": ["198.51.100.80/28"], '
                                          '"destinations": ["192.0.2.14"], "ports": ["22"], "protocol": "TCP", '
                                          '"translated_address": "10.104.20.14"}]}', "translated_port"),
}


@pytest.mark.parametrize("text, why", BAD_REPLIES.values(), ids=BAD_REPLIES.keys())
def test_a_reply_that_breaks_the_contract_is_refused(text, why):
    with pytest.raises(AgentError, match=re.escape(why) if why.startswith("'") else why):
        parse_reply(text)


# ------------------------------------------------------------ the call

def mcp_call(name, answer):
    """One mcp_call output item, as the Responses API lists a tool call and its answer."""
    return SimpleNamespace(type="mcp_call", name=name, output=json.dumps(answer))


def read(commit):
    """A tool answer that read main at commit."""
    return {"match": None, "source": {"files": ["data/network/routing.yaml"], "commit": commit}}


class FakeResponses:
    """Stands in for openai.responses: returns one canned response and records each request."""

    def __init__(self, text, fail=None, calls=None):
        self.text, self.fail, self.requests = text, fail, []
        self.calls = [mcp_call("locate_address_for_env_site", read(SNAP))] if calls is None else calls

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.fail:
            raise self.fail
        return SimpleNamespace(output_text=self.text, usage=SimpleNamespace(input_tokens=1200, output_tokens=80),
                               output=[*self.calls, SimpleNamespace(type="message")])


def foundry(text, fail=None, calls=None):
    """A FoundryAgent on fake clients, pinned to version 7 and snapshot SNAP."""
    return FoundryAgent(SimpleNamespace(), SimpleNamespace(responses=FakeResponses(text, fail, calls)), "7", SNAP)


def test_a_call_sends_only_the_ticket_and_review_to_the_pinned_version_and_records_its_use():
    data = yaml.safe_load((REQUESTS / "validation" / "validation_RITM0011061.yaml").read_text())
    a = foundry('{"outcome": "stop_and_ask", "reason": "both_ends_onprem", "rules": []}')
    reply = a(copy.deepcopy(data["ticket"]))
    sent = a.openai.responses.requests[0]
    assert reply["reason"] == "both_ends_onprem"
    assert sent["extra_body"] == {"agent_reference": {"name": AGENT_NAME, "version": "7", "type": "agent_reference"}}
    assert json.loads(sent["input"]) == {"ticket": data["ticket"], "engineer_review": None}
    call = a.calls[0]
    assert (call.number, call.input_tokens, call.output_tokens, call.tools, call.commits) == (
        "RITM0011061", 1200, 80, ["locate_address_for_env_site"], [SNAP])


def test_a_failed_call_or_an_invalid_reply_is_an_agent_error_and_is_recorded():
    with pytest.raises(AgentError, match="the agent call failed: TimeoutError"):
        foundry("", fail=TimeoutError("no answer"))({"number": "RITM0011001"})
    bad = foundry("I cannot help with that.")
    with pytest.raises(AgentError, match="not JSON"):
        bad({"number": "RITM0011001"})
    assert bad.calls[0].error.startswith("the agent's reply is not JSON")


def test_a_controlled_dns_condition_is_refused_without_a_call():
    a = foundry("{}")
    with pytest.raises(AgentError, match="DNS tool runs in Azure"):
        a({"number": "RITM0011069"}, dns_lookup=lambda host, rdtype: None)
    assert a.openai.responses.requests == []


STOP = '{"outcome": "stop_and_ask", "reason": "hub_rule", "rules": []}'
MIXED = {
    "second call read the new commit": [mcp_call("locate_address_for_env_site", read(SNAP)),
                                        mcp_call("duplicate_rule_check", {"matches": [], **read("d" * 40)})],
    "answer names no commit": [mcp_call("duplicate_rule_check", {"matches": []})],
    "answer is not JSON": [mcp_call("locate_address_for_env_site", "oops")],
}


@pytest.mark.parametrize("calls", MIXED.values(), ids=MIXED.keys())
def test_a_reply_built_on_any_tool_answer_from_another_revision_is_refused(calls):
    a = foundry(STOP, calls=calls)
    with pytest.raises(AgentError, match=f"not all from snapshot {SNAP[:12]}"):
        a({"number": "RITM0011066"})
    assert a.calls[0].error == "tool answers from another revision"


def test_refused_tool_calls_and_dns_answers_carry_no_revision_and_are_allowed():
    calls = [mcp_call("duplicate_rule_check", {"error": "bad_arguments", "reason": "type must be one of"}),
             mcp_call("dns_lookup_for_fqdn", {"host": "api.tailspin.example", "resolves": False}),
             mcp_call("duplicate_rule_check", {"matches": [], **read(SNAP)})]
    assert foundry(STOP, calls=calls)({"number": "RITM0011066"})["reason"] == "hub_rule"


def _git_repo(tmp_path):
    """A small git repo holding data/network and infra/envs, with one commit; return (root, sha)."""
    import subprocess
    root = tmp_path / "g"
    for rel in ("data/network/routing.yaml", "infra/envs/dev-eastus2/ip-groups.tfvars"):
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text("x\n")
    run = lambda *a: subprocess.run(["git", "-C", str(root), *a], check=True, capture_output=True, text=True).stdout  # noqa: E731
    run("init", "-q")
    run("add", ".")
    run("-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", "data")
    return root, run("rev-parse", "HEAD").strip()


def test_data_differences_finds_changed_and_untracked_data_files(tmp_path):
    root, sha = _git_repo(tmp_path)
    assert data_differences(root, sha) == []
    (root / "infra/envs/dev-eastus2/ip-groups.tfvars").write_text("changed\n")
    (root / "data/network/new.yaml").write_text("y\n")
    assert data_differences(root, sha) == ["data/network/new.yaml", "infra/envs/dev-eastus2/ip-groups.tfvars"]


def test_data_differences_refuses_a_commit_this_repo_does_not_have(tmp_path):
    root, _ = _git_repo(tmp_path)
    with pytest.raises(AgentError, match="cat-file"):
        data_differences(root, "e" * 40)


def test_from_env_refuses_when_the_repo_data_is_another_revision(tmp_path, monkeypatch):
    root, sha = _git_repo(tmp_path)
    (root / "data/network/routing.yaml").write_text("changed\n")
    monkeypatch.setenv("FWAGENT_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")
    monkeypatch.setenv("FWAGENT_SNAPSHOT_COMMIT", sha)
    with pytest.raises(AgentError, match="would use two revisions: data/network/routing.yaml"):
        FoundryAgent.from_env(root)


def test_from_env_needs_a_full_snapshot_sha(monkeypatch):
    monkeypatch.setenv("FWAGENT_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")
    monkeypatch.setenv("FWAGENT_SNAPSHOT_COMMIT", "main")
    with pytest.raises(AgentError, match="FWAGENT_SNAPSHOT_COMMIT must be the full SHA"):
        FoundryAgent.from_env(REPO)


def test_from_env_needs_the_project_endpoint(monkeypatch):
    monkeypatch.delenv("FWAGENT_PROJECT_ENDPOINT", raising=False)
    with pytest.raises(AgentError, match="FWAGENT_PROJECT_ENDPOINT is not set"):
        FoundryAgent.from_env(REPO)


# ------------------------------------------------------------ through fwagent accept

@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A copy of the network data and env-site files, with draft records in tmp_path/state."""
    import shutil
    root = tmp_path / "repo"
    shutil.copytree(REPO / "data" / "network", root / "data" / "network")
    shutil.copytree(REPO / "infra" / "envs", root / "infra" / "envs")
    monkeypatch.setenv("FWAGENT_STATE_DIR", str(tmp_path / "state"))
    return root


def _accept(repo, tmp_path, number):
    """Submit one validation ticket, then accept its exact version with no --reply."""
    data = yaml.safe_load((REQUESTS / "validation" / f"validation_{number}.yaml").read_text())
    path = tmp_path / f"{number}.yaml"
    path.write_text(yaml.safe_dump(data["ticket"]))
    assert cli.main(["submit", str(path)], repo=repo) == cli.REVIEW
    version = cli.load_record(repo, number)["ticket_version"][:12]
    return data, cli.main(["accept", number, "--ticket-version", version, "--engineer", "Jordan Patel",
                           "--reason", "checked"], repo=repo)


def test_accept_without_reply_or_endpoint_refuses_and_calls_nothing(repo, tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(cli, "live_agent", lambda root: pytest.fail("the live agent must not be built"))
    _, code = _accept(repo, tmp_path, "RITM0011001")
    assert code == cli.REFUSED and "set FWAGENT_PROJECT_ENDPOINT" in capsys.readouterr().out


def test_accept_with_the_endpoint_drafts_through_the_live_agent_and_records_it(repo, tmp_path, monkeypatch):
    monkeypatch.setenv("FWAGENT_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")
    data = yaml.safe_load((REQUESTS / "validation" / "validation_RITM0011001.yaml").read_text())
    fake = foundry(json.dumps(_reply_keys(data["expected"])))
    monkeypatch.setattr(cli, "live_agent", lambda root: fake)
    _, code = _accept(repo, tmp_path, "RITM0011001")
    record = cli.load_record(repo, "RITM0011001")
    assert code == cli.DONE and record["status"] == "drafted" and len(record["files"]) == 2
    assert record["history"][-1]["agent"] == "foundry"
    assert json.loads(fake.openai.responses.requests[0]["input"])["engineer_review"]["engineer"] == "Jordan Patel"


def test_a_live_agent_error_writes_nothing_and_leaves_the_ticket_waiting(repo, tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("FWAGENT_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")
    monkeypatch.setattr(cli, "live_agent", lambda root: foundry("not json"))
    before = {p: p.read_bytes() for p in (repo / "infra").rglob("*") if p.is_file()}
    _, code = _accept(repo, tmp_path, "RITM0011001")
    assert code == cli.REFUSED and "Nothing was written" in capsys.readouterr().out
    assert {p: p.read_bytes() for p in (repo / "infra").rglob("*") if p.is_file()} == before
    assert cli.load_record(repo, "RITM0011001")["status"] == "awaiting_review"
