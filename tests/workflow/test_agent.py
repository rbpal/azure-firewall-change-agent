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


def wrapped(reply: dict) -> str:
    """The agent's text for reply under strict output: {"reply": ...}."""
    return json.dumps({"reply": reply})


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

def test_the_definition_gives_four_read_tools_over_the_project_connection_with_no_approval_step():
    body = definition("x", "gpt-6-luna-agent", "mcp-fwagentic-tools")
    tool = body["tools"][0]
    assert body["model"] == "gpt-6-luna-agent" and len(body["tools"]) == 1
    assert tool["type"] == "mcp" and tool["project_connection_id"] == "mcp-fwagentic-tools"
    assert tool["server_url"] == "https://func-fwagentic-dev.azurewebsites.net/runtime/webhooks/mcp"
    assert sorted(tool["allowed_tools"]) == ["dnat_port_check", "dns_lookup_for_fqdn", "duplicate_rule_check",
                                             "locate_address_for_env_site", "resolve_env_site"]
    assert tool["require_approval"] == "never"
    # every tool call reads the commit the request supplies; the version itself names no commit
    assert tool["headers"] == {"X-Fwagent-Snapshot": "{{snapshot}}"}
    assert body["structured_inputs"] == {"snapshot": {"description": agent_mod.SNAPSHOT_INPUT_SPEC["description"],
                                                      "required": True, "schema": {"type": "string"}}}
    fmt = body["text"]["format"]
    assert fmt["type"] == "json_schema" and fmt["strict"] is True
    assert fmt["schema"] == json.loads((REPO / "agents" / "reply.strict.schema.json").read_text())


def test_the_definition_names_no_snapshot_so_new_network_data_needs_no_new_version():
    body = definition("x")
    assert SNAP not in json.dumps(body) and agent_mod.definition_sha(body) == agent_mod.definition_sha(definition("x"))
    assert agent_mod.definition_sha(definition("y")) != agent_mod.definition_sha(body)  # instructions still count


class FakeAgents:
    """Stands in for project.agents: lists versions and records each create_version."""

    def __init__(self, versions=(), missing=False):
        self.versions, self.missing, self.created = list(versions), missing, []

    def get_version(self, name, version):
        """The published version as Foundry returns it: metadata plus a dict-like definition."""
        for v in self.versions:
            if str(v.version) == str(version):
                return v
        for i, (_, made, metadata) in enumerate(self.created):
            if str(len(self.versions) + i + 1) == str(version):
                found = {"tools": [{"headers": made.tools[0].headers}],
                         "structured_inputs": {k: {"required": d.required} for k, d in made.structured_inputs.items()}}
                return SimpleNamespace(version=version, metadata=metadata, definition=found)
        raise type("ResourceNotFoundError", (Exception,), {"status_code": 404})("no version")

    def list_versions(self, name):
        if self.missing:
            raise type("ResourceNotFoundError", (Exception,), {"status_code": 404})("no agent")
        return self.versions

    def create_version(self, name, definition, metadata, description):
        self.created.append((name, definition, metadata))
        return SimpleNamespace(version=str(len(self.versions) + len(self.created)))


def test_an_unchanged_definition_reuses_its_version_and_a_changed_one_makes_a_new_version():
    body = definition("instructions v1")
    sha = agent_mod.definition_sha(body)
    same = FakeAgents([SimpleNamespace(version="3", metadata={"definition_sha": sha})])
    assert ensure_version(SimpleNamespace(agents=same), body) == "3" and same.created == []
    other = FakeAgents([SimpleNamespace(version="3", metadata={"definition_sha": sha})])
    assert ensure_version(SimpleNamespace(agents=other), definition("instructions v2")) == "2"
    name, made, metadata = other.created[0]
    assert name == AGENT_NAME and made.model == "gpt-6-luna-agent" and made.instructions == "instructions v2"
    assert made.tools[0].project_connection_id == "mcp-fwagentic-tools" and made.tools[0].require_approval == "never"
    assert made.tools[0].headers == {"X-Fwagent-Snapshot": "{{snapshot}}"}
    assert made.structured_inputs["snapshot"].required is True
    assert made.text.format.strict is True and made.text.format.name == "fwagent_reply"
    assert made.text.format.schema["properties"] == {"reply": made.text.format.schema["properties"]["reply"]}
    assert metadata["definition_sha"] != sha


def test_the_first_version_is_created_when_no_agent_exists():
    agents = FakeAgents(missing=True)
    assert ensure_version(SimpleNamespace(agents=agents), definition("x")) == "1"


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

    def __init__(self, text, fail=None, calls=None, **fields):
        self.text, self.fail, self.requests, self.fields = text, fail, [], fields
        self.calls = [mcp_call("locate_address_for_env_site", read(SNAP))] if calls is None else calls

    def create(self, **kwargs):
        self.requests.append(kwargs)
        if self.fail:
            raise self.fail
        return SimpleNamespace(output_text=self.text, usage=SimpleNamespace(input_tokens=1200, output_tokens=80),
                               output=[*self.calls, SimpleNamespace(type="message")], **self.fields)


def foundry(text, fail=None, calls=None, **fields):
    """A FoundryAgent on fake clients, pinned to version 7 and snapshot SNAP; fields are extra response fields."""
    return FoundryAgent(SimpleNamespace(), SimpleNamespace(responses=FakeResponses(text, fail, calls, **fields)), "7", SNAP)


def test_a_call_sends_only_the_ticket_and_review_to_the_pinned_version_and_records_its_use():
    data = yaml.safe_load((REQUESTS / "validation" / "validation_RITM0011061.yaml").read_text())
    a = foundry(wrapped({"outcome": "stop_and_ask", "reason": "both_ends_onprem", "rules": [],
                         "explanation": "Both ends are on-prem."}))
    reply = a(copy.deepcopy(data["ticket"]))
    sent = a.openai.responses.requests[0]
    assert reply["reason"] == "both_ends_onprem"
    assert sent["extra_body"] == {"agent_reference": {"name": AGENT_NAME, "version": "7", "type": "agent_reference"},
                                  "structured_inputs": {"snapshot": SNAP}}  # every tool call reads this commit
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


def _api_error(cls, status, body, headers=None):
    """An openai error as the agent service returns it, with its status, body and headers."""
    import httpx2
    import openai
    response = httpx2.Response(status, headers=headers or {}, request=httpx2.Request("POST", "https://example.test"))
    return getattr(openai, cls)(f"Error code: {status}", response=response, body=body)


@pytest.mark.parametrize("cls, status, body, headers, wait", [
    ("InternalServerError", 500, {"code": "rate_limit_exceeded", "message": "Rate limit is exceeded."},
     {"retry-after-ms": "12000"}, 12.0),
    ("RateLimitError", 429, {"code": "429", "message": "Too many requests."}, {"retry-after": "7"}, 7.0),
    ("RateLimitError", 429, None, None, None),
    ("InternalServerError", 500, {"error": {"code": "rate_limit_exceeded"}}, None, None),
])
def test_a_throttled_call_is_rate_limited_with_its_wait_and_is_recorded(cls, status, body, headers, wait):
    a = foundry("", fail=_api_error(cls, status, body, headers))
    with pytest.raises(agent_mod.RateLimited, match="the agent call failed") as raised:
        a({"number": "RITM0011002"})
    assert raised.value.retry_after == wait and isinstance(raised.value, agent_mod.InfraError)
    assert a.calls[0].error.startswith(cls)


@pytest.mark.parametrize("fail", [
    TimeoutError("no answer"),
    _api_error("AuthenticationError", 401, {"code": "unauthorized"}),
    _api_error("InternalServerError", 500, {"code": "server_error", "message": "boom"}),
])
def test_other_failed_calls_are_infrastructure_errors_but_not_rate_limits(fail):
    with pytest.raises(agent_mod.InfraError) as raised:
        foundry("", fail=fail)({"number": "RITM0011002"})
    assert not isinstance(raised.value, agent_mod.RateLimited)


def test_an_invalid_reply_is_a_model_error_not_an_infrastructure_error():
    with pytest.raises(AgentError) as raised:
        foundry(wrapped({"outcome": "stop_and_ask", "rules": [], "explanation": "x"}))({"number": "RITM0011033"})  # no reason, as 0033 replied
    assert not isinstance(raised.value, agent_mod.InfraError) and "reason" in str(raised.value)


def error(code):
    """The error object a finished but failed response carries."""
    return SimpleNamespace(code=code, message=f"{code} message")


def test_a_returned_response_that_failed_on_the_rate_limit_is_rate_limited_never_a_reply():
    # the service can answer without raising and mark the response failed; its text must never be scored
    a = foundry(STOP, status="failed", error=error("rate_limit_exceeded"))
    with pytest.raises(agent_mod.RateLimited, match="rate_limit_exceeded") as raised:
        a({"number": "RITM0011003"})
    assert raised.value.retry_after is None
    call = a.calls[0]
    assert "status failed" in call.error and "rate_limit_exceeded" in call.error
    assert (call.input_tokens, call.output_tokens) == (1200, 80)  # what the service reports is still counted


@pytest.mark.parametrize("status, code", [("failed", "server_error"), ("failed", None), ("cancelled", None),
                                          ("in_progress", None), ("queued", None)])
def test_a_returned_response_the_service_did_not_finish_is_an_infrastructure_error(status, code):
    a = foundry(STOP, status=status, error=error(code) if code else None)
    with pytest.raises(agent_mod.InfraError, match=f"status {status}") as raised:
        a({"number": "RITM0011003"})
    assert not isinstance(raised.value, agent_mod.RateLimited) and f"status {status}" in a.calls[0].error


def test_a_returned_response_failed_on_its_content_is_the_agents_failure_not_infrastructure():
    a = foundry(STOP, status="failed", error=error("invalid_prompt"))
    with pytest.raises(AgentError, match="invalid_prompt") as raised:
        a({"number": "RITM0011003"})
    assert not isinstance(raised.value, agent_mod.InfraError)


def test_an_incomplete_response_is_refused_even_when_its_text_is_a_valid_reply():
    a = foundry(STOP, status="incomplete", incomplete_details=SimpleNamespace(reason="max_output_tokens"))
    with pytest.raises(AgentError, match="incomplete: max_output_tokens") as raised:
        a({"number": "RITM0011003"})
    assert not isinstance(raised.value, agent_mod.InfraError)
    assert a.calls[0].error.startswith("the agent's response is incomplete: max_output_tokens")


@pytest.mark.parametrize("fields", [{"status": "completed", "error": None}, {}], ids=["completed", "no status field"])
def test_a_completed_response_is_still_read_as_a_reply(fields):
    assert foundry(STOP, **fields)({"number": "RITM0011003"})["reason"] == "hub_rule"


def test_a_controlled_dns_condition_is_refused_without_a_call():
    a = foundry("{}")
    with pytest.raises(AgentError, match="DNS tool runs in Azure"):
        a({"number": "RITM0011069"}, dns_lookup=lambda host, rdtype: None)
    assert a.openai.responses.requests == []


STOP = wrapped({"outcome": "stop_and_ask", "reason": "hub_rule", "rules": [], "explanation": "The rule is in the hub group."})
MIXED = {
    "second call read the new commit": [mcp_call("locate_address_for_env_site", read(SNAP)),
                                        mcp_call("duplicate_rule_check", {"matches": [], **read("d" * 40)})],
    "answer names no commit": [mcp_call("duplicate_rule_check", {"matches": []})],
    "answer is not JSON": [mcp_call("locate_address_for_env_site", "oops")],
    "env-site answer read the new commit": [mcp_call("resolve_env_site", {"resolved": True, **read("d" * 40)})],
    "env-site answer names no commit": [mcp_call("resolve_env_site", {"resolved": True, "match": None})],
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


def test_accept_without_reply_or_endpoint_refuses_and_calls_nothing(repo, tmp_path, capsys, monkeypatch, offline_main):
    monkeypatch.setattr(cli, "live_agent", lambda *_: pytest.fail("the live agent must not be built"))
    _, code = _accept(repo, tmp_path, "RITM0011001")
    assert code == cli.REFUSED and "set FWAGENT_PROJECT_ENDPOINT" in capsys.readouterr().out


def test_accept_with_the_endpoint_drafts_through_the_live_agent_and_records_it(repo, tmp_path, monkeypatch, offline_main):
    monkeypatch.setenv("FWAGENT_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")
    data = yaml.safe_load((REQUESTS / "validation" / "validation_RITM0011001.yaml").read_text())
    fake = foundry(wrapped({**_reply_keys(data["expected"]), "explanation": "Drafted for both selected sites."}))
    monkeypatch.setattr(cli, "live_agent", lambda *_: fake)
    _, code = _accept(repo, tmp_path, "RITM0011001")
    record = cli.load_record(repo, "RITM0011001")
    assert code == cli.DONE and record["status"] == "drafted" and len(record["files"]) == 2
    assert [h["action"] for h in record["history"][-2:]] == ["accept", "draft"]
    assert record["history"][-1]["agent"] == "foundry" and record["drafting"]["main_commit"] == "a" * 40
    assert json.loads(fake.openai.responses.requests[0]["input"])["engineer_review"]["engineer"] == "Jordan Patel"


def test_a_live_agent_error_writes_nothing_and_keeps_the_acceptance(repo, tmp_path, capsys, monkeypatch, offline_main):
    monkeypatch.setenv("FWAGENT_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")
    monkeypatch.setattr(cli, "live_agent", lambda *_: foundry("not json"))
    before = {p: p.read_bytes() for p in (repo / "infra").rglob("*") if p.is_file()}
    _, code = _accept(repo, tmp_path, "RITM0011001")
    out = capsys.readouterr().out
    assert code == cli.REFUSED and "Nothing was written" in out and "Your acceptance is kept" in out
    assert {p: p.read_bytes() for p in (repo / "infra").rglob("*") if p.is_file()} == before
    record = cli.load_record(repo, "RITM0011001")
    assert record["status"] == "accepted" and record["review"]["ticket_version"] == record["ticket_version"]


def _step_one() -> str:
    """Step 1 of the drafter's instructions, as the agent reads it."""
    text = (Path(__file__).resolve().parents[2] / "agents" / "drafter.md").read_text()
    return text[text.index("1. Pick the runbook"):text.index("2. Get every fact")]


def test_step_one_checks_mixed_sources_and_unresolved_groups_before_any_route():
    step = _step_one()
    order = ["- a. ", "`origin: mixed`", "- b. ", "`origin: null`", "- c. ", "`open_dnat_source`", "- d. ",
             "`address_not_in_plan`", "- e. ", "`address_space: mixed`", "- f. ", "RB-01", "- g. ", "- h. ", "evaluate the ticket with RB-02", "- i. "]
    at = [step.index(word, step.index("- a. ")) for word in order]
    assert at == sorted(at)
    assert all(step.index(word) > step.index("- a. ") for word in ("`open_dnat_source`", "`address_not_in_plan`", "evaluate the ticket with RB-02"))


def test_step_one_requires_the_open_source_lookup_before_the_stop():
    assert "`0.0.0.0/0` must be looked up before you stop" in _step_one()
    assert "The tool refuses `*`, so do not look it up." in _step_one()


def test_rb_03_treats_an_exact_match_on_a_removal_as_a_deletion_candidate():
    text = (Path(__file__).resolve().parents[2] / "data" / "runbooks" / "rule-removal.md").read_text()
    section = text[text.index("## RB-03-1"):text.index("## RB-03-2")]
    assert "identifies an existing matching rule. Treat it as a deletion candidate" in section
    assert "Do not conclude that no removal is needed merely because the requested traffic is already allowed." in section


def test_the_recorded_tool_calls_keep_each_name_and_its_arguments():
    good = SimpleNamespace(type="mcp_call", name="locate_address_for_env_site", arguments='{"address": "0.0.0.0/0"}')
    bad = SimpleNamespace(type="mcp_call", name="resolve_env_site", arguments="oops")
    other = SimpleNamespace(type="message")
    assert agent_mod.tool_calls(SimpleNamespace(output=[good, bad, other])) == [
        {"name": "locate_address_for_env_site", "arguments": {"address": "0.0.0.0/0"}},
        {"name": "resolve_env_site", "arguments": {}}]


def test_step_one_never_lets_a_tag_or_name_or_address_space_prove_direction():
    step = _step_one()
    assert "never from the ticket's `environment`, `site` or `location` tags or from a group's name" in step
    assert "`non_rfc1918` does not prove the source is on the internet" in step
    assert "Every RB-02 check still decides" in step


def test_the_unresolved_stop_goes_back_for_edit_or_reject_and_a_new_acceptance():
    text = (Path(__file__).resolve().parents[2] / "agents" / "drafter.md").read_text()
    assert "return the ticket to the engineer to edit or reject" in text
    assert "An edited ticket must be accepted again before you run again" in text
