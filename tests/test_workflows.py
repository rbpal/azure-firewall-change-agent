"""Safety rules for the GitHub Actions workflows, checked on every test run.

Example: if someone switches the gate to pull_request_target, or adds an
env-site root without planning it, these tests fail.
Why: the plan job holds an Azure token; a wrong trigger or a missing root
weakens the gate without any error showing.
Safety rule: the gate only reads. It never applies and never takes the state lock.
"""

import re
import subprocess
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
    [check] = [r for r in run_steps(SYNC) if "git ls-tree" in r]
    assert set(re.search(r'--name-only "\$TARGET" -- (.+?) \|', check).group(1).split()) == TOOL_DATA


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


def sync_step(name: str) -> dict:
    """The sync job's step with this name."""
    [step] = [s for s in load(SYNC)["jobs"]["sync"]["steps"] if s.get("name") == name]
    return step


def choose(rollback_to: str, tmp_path: Path) -> tuple[int, str]:
    """Run the 'Choose the commit' step in this repo; return its exit code and what it wrote to GITHUB_ENV."""
    env_file = tmp_path / "github_env"
    env_file.write_text("")
    env = {"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin", "GITHUB_REF": "refs/heads/main",
           "GITHUB_SHA": "pushed-commit", "GITHUB_ENV": str(env_file), "ROLLBACK_TO": rollback_to}
    run = sync_step("Choose the commit")["run"]
    code = subprocess.run(["bash", "-e", "-c", run], cwd=REPO, env=env, capture_output=True).returncode
    return code, env_file.read_text()


def test_sync_keeps_two_snapshots():
    # User decision 2026-10-22: the current snapshot and the one before it, nothing more.
    assert load(SYNC)["env"]["KEEP"] == "2"


def test_sync_rollback_input_reaches_the_shell_only_as_an_environment_variable():
    # ${{ }} inside run: is pasted into the script before it runs, so input text could become commands.
    assert load(SYNC)["on"]["workflow_dispatch"]["inputs"]["rollback_to"]["default"] == ""
    assert sync_step("Choose the commit")["env"] == {"ROLLBACK_TO": "${{ inputs.rollback_to }}"}
    assert not any("${{" in r for r in run_steps(SYNC))


@pytest.mark.parametrize("bad", ["abc", "HEAD", "0" * 40, "$(id)", "A" * 40, "0" * 40 + "\nx"])
def test_sync_rollback_refuses_anything_but_a_full_sha_on_main(bad, tmp_path):
    code, written = choose(bad, tmp_path)
    assert code != 0 and written == ""


def test_sync_rollback_chooses_a_commit_on_main(tmp_path):
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True).stdout.strip()
    assert choose(head, tmp_path) == (0, f"TARGET={head}\n")


def test_sync_without_rollback_chooses_the_pushed_commit(tmp_path):
    assert choose("", tmp_path) == (0, "TARGET=pushed-commit\n")


def test_sync_rollback_uploads_nothing_and_deletes_nothing():
    only_on_sync = "github.event_name == 'push' || inputs.rollback_to == ''"
    assert sync_step("Upload this commit's files")["if"] == only_on_sync
    assert sync_step("Delete old copies")["if"] == only_on_sync
    assert "if" not in sync_step("Check the snapshot is complete")
    assert "if" not in sync_step("Point current.json at the chosen commit")


def test_sync_points_at_the_checked_commit_and_never_deletes_it():
    check = sync_step("Check the snapshot is complete")["run"]
    assert 'git ls-tree -r --name-only "$TARGET"' in check and "diff wanted.txt uploaded.txt" in check
    assert '"$TARGET" > current.json' in sync_step("Point current.json at the chosen commit")["run"]
    assert '[ "$old" = "$TARGET" ] && continue' in sync_step("Delete old copies")["run"]
    assert "$GITHUB_SHA" not in check + sync_step("Delete old copies")["run"]


def test_sync_checkout_has_history_for_a_rollback():
    [checkout] = [s for s in load(SYNC)["jobs"]["sync"]["steps"] if s.get("uses", "").startswith("actions/checkout@")]
    assert checkout["with"]["fetch-depth"] == 0
