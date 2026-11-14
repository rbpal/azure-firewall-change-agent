"""Deploying a main commit's mcp/ code to the tool server and checking it runs that code. Every check must be able to fail.

No test reaches Azure: the deployed server is a reader that answers a code hash, and the deploy is a stand-in.
"""

import subprocess
import zipfile
from pathlib import Path

import pytest

import workflow.tool_deploy as tool_deploy
from workflow import tool_server
from workflow.agent import AgentError

REPO = Path(__file__).resolve().parents[2]
HEAD = subprocess.run(["git", "-C", str(REPO), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
MAIN = tool_server.main_code(REPO, HEAD)
OLD = {"code_sha256": "0" * 64, "files": {**MAIN["files"], "tools/duplicate_rule_check.py": "1" * 64}}


class Server:
    """A tool server that answers `before` until the deploy, then `after`, read by read."""

    def __init__(self, before, after=(MAIN,)):
        self.answers, self.after, self.deploys, self.reads = list(before), list(after), [], 0

    def read(self):
        """Answer the next code hash; an AgentError answer is raised, as an unreachable server would."""
        self.reads += 1
        queue = self.after if self.deploys else self.answers
        answer = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(answer, Exception):
            raise answer
        return answer

    def deploy(self, repo, commit):
        """Record a deploy of commit."""
        self.deploys.append(commit)


def ensure(server, **kw):
    """ensure_tool_code with the stand-in server, no real waiting, and a short deadline."""
    clock = iter(range(0, 10_000, 20))
    return tool_deploy.ensure_tool_code(REPO, HEAD, reader=server.read, deployer=server.deploy, sleep=lambda s: None,
                                        clock=lambda: next(clock), timeout=100, interval=20, **kw)


def test_a_server_already_running_the_commits_code_is_not_redeployed():
    server = Server([MAIN])
    record = ensure(server)
    assert server.deploys == [] and record["deployed"] is False
    assert (record["commit"], record["code_sha256"]) == (HEAD, MAIN["code_sha256"])


def test_a_server_running_other_code_gets_the_commits_code_then_is_checked_again():
    server = Server([OLD], after=[OLD, MAIN])  # the first read after the deploy still sees the old code
    record = ensure(server)
    assert server.deploys == [HEAD] and record["deployed"] is True and record["code_sha256"] == MAIN["code_sha256"]
    assert server.reads == 3


def test_a_server_that_cannot_be_read_counts_as_different_and_is_deployed_then_checked():
    server = Server([AgentError("could not reach the tool server")], after=[AgentError("restarting"), MAIN])
    assert ensure(server)["deployed"] is True and server.deploys == [HEAD]


def test_code_that_never_matches_before_the_deadline_fails_and_names_the_file():
    server = Server([OLD], after=[OLD])
    with pytest.raises(AgentError, match=r"still does not run that code \(tools/duplicate_rule_check.py\)"):
        ensure(server)
    assert server.deploys == [HEAD]  # deployed once, never in a loop


def test_a_failed_deploy_stops_before_any_check_counts():
    def broken(repo, commit):
        raise AgentError("deploying mcp/ failed: Forbidden")
    with pytest.raises(AgentError, match="Forbidden"):
        tool_deploy.ensure_tool_code(REPO, HEAD, reader=lambda: OLD, deployer=broken, sleep=lambda s: None)


def test_the_package_holds_the_commits_mcp_tree_and_nothing_else(tmp_path):
    names = set(zipfile.ZipFile(tool_deploy.package(REPO, HEAD, tmp_path / "mcp.zip")).namelist())
    assert {"function_app.py", "host.json", "requirements.txt", "tools/duplicate_rule_check.py"} <= names
    assert not any(n.startswith(("mcp/", "workflow/", "evals/", "infra/", "data/")) for n in names)
    tracked = subprocess.run(["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", HEAD, "--", "mcp"],
                             capture_output=True, text=True, check=True).stdout.split()
    assert {n for n in names if not n.endswith("/")} == {p.removeprefix("mcp/") for p in tracked}  # Git's bytes only


def test_the_deploy_command_is_a_remote_build_to_the_one_function_app(monkeypatch):
    seen = []

    def fake_run(cmd, **kw):
        seen.append(cmd)
        if cmd[0] == "git":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"zip")
        return subprocess.CompletedProcess(cmd, 0, "", "")
    monkeypatch.setattr(tool_deploy.subprocess, "run", fake_run)
    tool_deploy.config_zip(REPO, HEAD)
    az = seen[-1]
    assert az[:5] == ["az", "functionapp", "deployment", "source", "config-zip"]
    assert az[az.index("-n") + 1] == "func-fwagentic-dev" and az[az.index("-g") + 1] == "rg-fwagentic-dev"
    assert az[az.index("--build-remote") + 1] == "true"
    assert seen[0][-1] == f"{HEAD}:mcp"


def test_a_deploy_that_az_reports_as_failed_raises(monkeypatch):
    def fake_run(cmd, **kw):
        if cmd[0] == "git":
            Path(cmd[cmd.index("-o") + 1]).write_bytes(b"zip")
            return subprocess.CompletedProcess(cmd, 0, "", "")
        return subprocess.CompletedProcess(cmd, 1, "", "AuthorizationFailed")
    monkeypatch.setattr(tool_deploy.subprocess, "run", fake_run)
    with pytest.raises(AgentError, match="AuthorizationFailed"):
        tool_deploy.config_zip(REPO, HEAD)
