"""Safety rules for the GitHub Actions workflows, checked on every test run.

Example: if someone switches the gate to pull_request_target, or adds an
env-site root without planning it, these tests fail.
Why: the plan job holds an Azure token; a wrong trigger or a missing root
weakens the gate without any error showing.
Safety rule: the gate only reads. It never applies and never takes the state lock.
"""

import re
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[1]
WORKFLOWS = sorted((REPO / ".github" / "workflows").glob("*.yml"))
GATE = REPO / ".github" / "workflows" / "tier1-gate.yml"
SYNC = REPO / ".github" / "workflows" / "sync-network.yml"
TESTS = REPO / ".github" / "workflows" / "tests.yml"
# The only folders the agent's tools may read. evals/ holds the eval answers.
TOOL_DATA = {"data/network", "infra/envs"}


def load(path: Path) -> dict:
    """Parse a workflow; YAML reads the key `on` as True, so put it back."""
    data = yaml.safe_load(path.read_text())
    if True in data:
        data["on"] = data.pop(True)
    return data


def run_steps(path: Path) -> list[str]:
    """The shell text of every run step in a workflow."""
    return [s["run"] for job in load(path)["jobs"].values() for s in job["steps"] if "run" in s]


def triggers(data: dict) -> set[str]:
    """The event names a workflow runs on."""
    on = data["on"]
    return {on} if isinstance(on, str) else set(on)


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_runs_fork_code_with_repo_rights(path):
    assert not triggers(load(path)) & {"pull_request_target", "workflow_run"}


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_every_action_is_pinned_to_a_commit(path):
    for job in load(path)["jobs"].values():
        for step in job["steps"]:
            if "uses" in step:
                ref = step["uses"].split("@", 1)[1]
                assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), step["uses"]


def test_gate_plans_every_env_site_root():
    roots = {p.parent.name for p in (REPO / "infra" / "envs").glob("*/main.tf")}
    assert set(load(GATE)["jobs"]["plan"]["strategy"]["matrix"]["env_site"]) == roots


def test_only_the_plan_job_gets_an_azure_token():
    data = load(GATE)
    assert data["permissions"] == {"contents": "read"}
    with_token = [n for n, j in data["jobs"].items() if (j.get("permissions") or {}).get("id-token") == "write"]
    assert with_token == ["plan"]


def test_plan_job_runs_on_pull_requests_from_this_repo_only():
    cond = load(GATE)["jobs"]["plan"]["if"]
    assert "github.event_name == 'pull_request'" in cond
    assert "head.repo.full_name == github.repository" in cond


def test_gate_never_applies_and_never_locks_state():
    text = GATE.read_text()
    run = "\n".join(s.get("run", "") for j in load(GATE)["jobs"].values() for s in j["steps"])
    assert "apply" not in run and "-lock=false" in run
    assert "upload-artifact" not in text  # plan JSON holds resource IDs


def test_gate_signs_in_as_the_plan_identity():
    logins = [s for s in load(GATE)["jobs"]["plan"]["steps"] if s.get("uses", "").startswith("azure/login@")]
    assert [s["with"]["client-id"] for s in logins] == ["${{ secrets.AZURE_PLAN_CLIENT_ID }}"]


def test_sync_uploads_only_the_tool_data():
    # The agent's tools read this copy. Any other folder uploaded, such as
    # evals/ with the answers, would be readable by the agent.
    [upload] = [r for r in run_steps(SYNC) if "upload-batch" in r]
    assert set(re.search(r"for dir in ([^;]+);", upload).group(1).split()) == TOOL_DATA
    [count] = [r for r in run_steps(SYNC) if "find " in r]
    assert set(re.search(r"find (.+?) -type f", count).group(1).split()) == TOOL_DATA


@pytest.mark.parametrize("path", WORKFLOWS, ids=lambda p: p.name)
def test_no_workflow_uploads_the_eval_answers(path):
    for run in run_steps(path):
        if "az storage" in run:
            assert "evals" not in run


def test_tests_workflow_mutation_tests_the_scorers_after_the_suite():
    # The scorers are the gate before Foundry spend; a weakened scorer must turn CI red.
    runs = run_steps(TESTS)
    assert runs[-1] == "uv run --python 3.11 python evals/mutate_scorers.py"
    assert any(r.startswith("uv run --python 3.11 pytest") for r in runs[:-1])
