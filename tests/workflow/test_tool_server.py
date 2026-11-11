"""The deployed-code check: the tool server's code hash must equal main's mcp/ hash before any agent call.

Offline: a fake reader or a fake HTTP layer stands in for func-fwagentic-dev. Each test fails if the check
passes a stale server, blames the wrong file, or lets the agent run without the check.
"""

import json
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

import workflow.agent as agent_mod
import workflow.tool_server as ts
from workflow.agent import AgentError, FoundryAgent

REPO = Path(__file__).resolve().parents[2]
REAL_CHECK = ts.check  # tests/conftest.py replaces ts.check for every other test; these test the real one
REAL_RULE = ts.rule(REPO)


def git(repo: Path, *args: str) -> str:
    """Run git in repo and return its trimmed output."""
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """A one-commit repo holding the real rule file and a small mcp/ folder; returns (path, commit)."""
    root = tmp_path / "repo"
    (root / "mcp" / "tools").mkdir(parents=True)
    (root / "mcp" / "tools" / "code_version.py").write_bytes((REPO / ts.RULE).read_bytes())
    (root / "mcp" / "gateway.py").write_text("def run(): pass\n")
    (root / "mcp" / "host.json").write_text("{}\n")
    (root / "mcp" / "README.md").write_text("not code\n")
    (root / "data").mkdir()
    (root / "data" / "x.yaml").write_text("not mcp\n")
    (root / "data" / "helper.py").write_text("python, but outside mcp/\n")
    git(tmp_path, "init", "-q", str(root))
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "one")
    return root, git(root, "rev-parse", "HEAD")


def served(root: Path) -> dict:
    """What the tool on a server deployed from root/mcp would report."""
    return REAL_RULE.code_version(None, {}, root=root / "mcp")


# ------------------------------------------------------------ the rule both sides share


@pytest.mark.parametrize("path,expected", [
    ("gateway.py", True), ("tools/resolve_env_site.py", True), ("host.json", True), ("requirements.txt", True),
    ("README.md", False), ("tools/README.md", False), (".funcignore", False), ("tools/host.json", False),
    ("__pycache__/gateway.cpython-311.py", False), (".python_packages/lib/x.py", False),
])
def test_the_hash_covers_code_files_only(path, expected):
    assert REAL_RULE.covered(path) is expected


def test_one_changed_byte_changes_the_code_hash():
    one = REAL_RULE.fingerprint({"a.py": b"x = 1\n"})
    assert one != REAL_RULE.fingerprint({"a.py": b"x = 2\n"})
    assert one != REAL_RULE.fingerprint({"a.py": b"x = 1\n", "b.py": b""}), "an added file must change it"
    assert one == REAL_RULE.fingerprint({"a.py": b"x = 1\n", "README.md": b"docs"}), "docs must not change it"


def test_the_server_skips_installed_packages_and_virtual_environments(tmp_path):
    (tmp_path / "gateway.py").write_text("x\n")
    for folder in (".python_packages/lib", "__pycache__", "antenv"):
        (tmp_path / folder).mkdir(parents=True)
        (tmp_path / folder / "pkg.py").write_text("installed\n")
    (tmp_path / "antenv" / "pyvenv.cfg").write_text("home = /usr\n")
    assert set(REAL_RULE.code_version(None, {}, root=tmp_path)["files"]) == {"gateway.py"}


def test_the_tool_answers_only_hashes_never_file_contents(repo):
    root, _ = repo
    answer = served(root)
    assert set(answer) == {"code_sha256", "files"}
    assert "def run" not in json.dumps(answer)


# ------------------------------------------------------------ main's hash and the comparison


def test_mains_hash_equals_what_a_server_deployed_from_main_reports(repo):
    root, commit = repo
    assert ts.main_code(root, commit) == served(root)
    assert set(ts.main_code(root, commit)["files"]) == {"gateway.py", "host.json", "tools/code_version.py"}


def test_mains_hash_comes_from_the_commit_not_the_working_tree(repo):
    root, commit = repo
    before = ts.main_code(root, commit)
    (root / "mcp" / "gateway.py").write_text("edited, not committed\n")
    assert ts.main_code(root, commit) == before


def test_a_server_running_mains_code_passes(repo):
    root, commit = repo
    assert REAL_CHECK(root, commit, reader=lambda: served(root)) == {
        "code_sha256": served(root)["code_sha256"], "files": 3}


def test_a_stale_server_is_refused_and_the_differing_file_is_named(repo):
    root, commit = repo
    (root / "mcp" / "gateway.py").write_text("def run(): return 'old'\n")  # what the old package held
    stale = served(root)
    git(root, "checkout", "-q", "--", "mcp/gateway.py")
    with pytest.raises(AgentError, match=r"does not run GitHub main's mcp/ code: 1 file\(s\) differ \(gateway.py\)") as e:
        REAL_CHECK(root, commit, reader=lambda: stale)
    assert e.value.detail["differing"] == ["gateway.py"] and e.value.detail["main_commit"] == commit


def test_a_server_missing_a_file_or_holding_an_extra_one_is_refused(repo):
    root, commit = repo
    main = ts.main_code(root, commit)
    missing = REAL_RULE.fingerprint({})  # holds nothing
    extra = {"code_sha256": "x", "files": {**main["files"], "tools/new.py": "0" * 64}}
    assert ts.problems(main, missing) == ["gateway.py", "host.json", "tools/code_version.py"]
    assert ts.problems(main, extra) == ["tools/new.py"]


def test_a_hash_mismatch_with_identical_file_lists_still_fails():
    main = {"code_sha256": "a", "files": {"x.py": "1"}}
    assert ts.problems(main, {"code_sha256": "b", "files": {"x.py": "1"}}) == ["the code hashes differ"]
    assert ts.problems(main, {"files": {"x.py": "1"}}) == ["the code hashes differ"]


# ------------------------------------------------------------ the MCP call


class FakeHttp:
    """Answers the three MCP messages like func-fwagentic-dev, from a chosen tool result."""

    def __init__(self, result=None, error=None, session="s-1"):
        """Keep the tool result or JSON-RPC error to answer with, and the session ID to hand out."""
        self.result, self.error, self.session, self.sent = result, error, session, []

    def __call__(self, url, body, headers):
        """Record the message and answer it."""
        self.sent.append((body.get("method"), dict(headers)))
        if body["method"] == "initialize":
            return {"jsonrpc": "2.0", "id": 1, "result": {}}, ({"mcp-session-id": self.session} if self.session else {})
        if body["method"].startswith("notifications/"):
            return None, {}
        if self.error:
            return {"jsonrpc": "2.0", "id": 2, "error": self.error}, {}
        return {"jsonrpc": "2.0", "id": 2, "result": self.result}, {}


def text_result(answer: dict) -> dict:
    """A tool result whose one text item holds answer as JSON."""
    return {"content": [{"type": "text", "text": json.dumps(answer)}]}


def test_the_call_sends_the_token_and_session_and_returns_the_tools_answer(monkeypatch):
    http = FakeHttp(text_result({"code_sha256": "h", "files": {}}))
    monkeypatch.setattr(ts, "post", http)
    assert ts.call_tool("https://x/mcp", "TOKEN", "code_version") == {"code_sha256": "h", "files": {}}
    assert [m for m, _ in http.sent] == ["initialize", "notifications/initialized", "tools/call"]
    assert all(h["Authorization"] == "Bearer TOKEN" for _, h in http.sent)
    assert http.sent[2][1]["Mcp-Session-Id"] == "s-1"


@pytest.mark.parametrize("http", [
    FakeHttp(error={"code": -32602, "message": "Unknown tool: code_version"}),
    FakeHttp({"isError": True, "content": [{"type": "text", "text": "boom"}]}),
    FakeHttp({"content": []}),
], ids=["unknown-tool", "tool-error", "empty"])
def test_a_server_without_a_working_code_version_tool_is_refused(monkeypatch, http):
    monkeypatch.setattr(ts, "post", http)
    with pytest.raises(AgentError, match="no working code_version tool, so it is older than this check"):
        ts.call_tool("https://x/mcp", "T", "code_version")


def test_a_refusal_from_the_gateway_is_a_failure_not_a_pass(monkeypatch):
    monkeypatch.setattr(ts, "post", FakeHttp(text_result({"error": "forbidden", "reason": "no Tools.Read"})))
    with pytest.raises(AgentError, match="refused code_version: no Tools.Read"):
        ts.call_tool("https://x/mcp", "T", "code_version")


@pytest.mark.parametrize("body,expected", [
    ('event: message\ndata: {"jsonrpc": "2.0", "id": 2}\n\n', {"jsonrpc": "2.0", "id": 2}),
    ('{"jsonrpc": "2.0", "id": 1}', {"jsonrpc": "2.0", "id": 1}),
    ("", None),
])
def test_event_stream_and_plain_json_answers_are_both_read(body, expected):
    assert ts.parse(body) == expected


def test_an_unreachable_server_is_an_error(monkeypatch):
    def refuse(request, timeout):
        raise OSError("connection refused")
    monkeypatch.setattr(ts.urllib.request, "urlopen", refuse)
    with pytest.raises(AgentError, match="could not reach the tool server"):
        ts.post("https://x/mcp", {"method": "initialize"}, {})


def test_the_audience_setting_overrides_the_entra_lookup(monkeypatch):
    monkeypatch.setenv("FWAGENT_MCP_AUDIENCE", "api://tool-server")
    monkeypatch.setattr(ts.subprocess, "run", lambda *a, **k: pytest.fail("Entra must not be asked"))
    assert ts.audience() == "api://tool-server"


@pytest.mark.parametrize("found,ok", [([["api://one"]], True), ([], False), ([["api://a"], ["api://b"]], False)])
def test_the_entra_lookup_needs_exactly_one_api_uri(monkeypatch, found, ok):
    monkeypatch.delenv("FWAGENT_MCP_AUDIENCE", raising=False)
    monkeypatch.setattr(ts.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=0, stdout=json.dumps(found)))
    if ok:
        assert ts.audience() == "api://one"
    else:
        with pytest.raises(AgentError, match="expected one api:// URI"):
            ts.audience()


def test_the_agent_is_never_given_the_code_version_tool():
    assert ts.TOOL not in agent_mod.TOOLS


# ------------------------------------------------------------ the hook: no agent without the check


def test_the_pinned_agent_is_refused_when_the_tool_server_is_stale(monkeypatch, tmp_path):
    """pinned() must call the check with the ticket branch and commit, after its other checks, and stop on failure."""
    commit = "d" * 40
    seen = []

    def stale(repo, at):
        seen.append((repo, at))
        raise AgentError("the deployed tool server does not run GitHub main's mcp/ code")

    monkeypatch.setenv("FWAGENT_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")
    monkeypatch.setattr(agent_mod, "data_differences", lambda repo, c: [])
    monkeypatch.setattr(agent_mod, "validators_behind", lambda repo: [])
    monkeypatch.setattr(agent_mod, "local_definition", lambda repo: {"d": 1})
    monkeypatch.setattr(agent_mod, "definition_sha", lambda body: "sha")
    monkeypatch.setattr(agent_mod, "check_version", lambda p, v, b: None)
    opened = []
    monkeypatch.setattr(agent_mod, "connect", lambda e: SimpleNamespace(
        get_openai_client=lambda **o: opened.append(o)))
    monkeypatch.setattr(ts, "check", stale)
    marker = {"commit": commit, "agent": {"version": "11", "definition_sha": "sha"}}
    with pytest.raises(AgentError, match="does not run GitHub main's mcp/ code"):
        FoundryAgent.pinned(tmp_path, commit, marker, require_evaluation=False)
    assert seen == [(tmp_path, commit)] and opened == [], "no model client may be opened for a stale server"
    monkeypatch.setattr(ts, "check", lambda repo, at: {"code_sha256": "h", "files": 14})
    assert FoundryAgent.pinned(tmp_path, commit, marker, require_evaluation=False).tool_code == {
        "code_sha256": "h", "files": 14}
