"""Drafting from GitHub main: snapshots, ready markers, agent versions and the draft loop. Every check must be able to fail.

The tests use real git repos in a temporary folder (a bare "origin", a clone that pushes to main,
and the engineer's clone) and an in-memory blob container. No test reaches Azure, GitHub or Foundry.
"""

import copy
import json
import re
import shutil
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

import workflow.cli as cli
import workflow.snapshot as snap

REAL_LIVE_AGENT = cli.live_agent  # captured before any test patches it
from tests.workflow.test_agent import FakeAgents, FakeResponses, mcp_call, read, wrapped
from workflow.agent import AgentError, FoundryAgent, definition_sha, local_definition
from workflow.deploy import mark_ready
from workflow.mainline import MainMoving, RunTooLong, draft_from_main, fetch_main

REPO = Path(__file__).resolve().parents[2]
REQUESTS = REPO / "evals" / "requests"
NOW = datetime(2026, 11, 3, 15, 0, tzinfo=timezone.utc)


class Blob(SimpleNamespace):
    """One listed blob: its name and when it was last written."""


class FakeContainer:
    """Stands in for the network-snapshot container: upload once, download, list, delete."""

    def __init__(self):
        self.blobs, self.modified = {}, {}

    def upload_blob(self, name, data, overwrite=False):
        if name in self.blobs and not overwrite:
            raise ResourceExistsError(name)
        self.blobs[name], self.modified[name] = bytes(data), NOW

    def download_blob(self, name):
        self.downloads = getattr(self, "downloads", []) + [name]
        if name not in self.blobs:
            raise ResourceNotFoundError(name)
        return SimpleNamespace(readall=lambda: self.blobs[name])

    def list_blobs(self, name_starts_with):
        return [Blob(name=n, last_modified=self.modified.get(n, NOW)) for n in sorted(self.blobs) if n.startswith(name_starts_with)]

    def delete_blob(self, name):
        del self.blobs[name], self.modified[name]


def git(root, *args):
    """Run git in root and return its output."""
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True, text=True).stdout


def commit_all(root, message):
    """Commit everything in root and return the new SHA."""
    git(root, "add", "-A")
    git(root, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-q", "-m", message)
    return git(root, "rev-parse", "HEAD").strip()


@pytest.fixture
def world(tmp_path, monkeypatch):
    """origin (bare), pusher (pushes to main) and engineer (the repo fwagent runs in), all on the real network data."""
    origin, pusher, engineer = tmp_path / "origin.git", tmp_path / "pusher", tmp_path / "engineer"
    subprocess.run(["git", "init", "-q", "--bare", str(origin)], check=True)  # git 2.21 here: no init -b
    git(origin, "symbolic-ref", "HEAD", "refs/heads/main")
    subprocess.run(["git", "clone", "-q", str(origin), str(pusher)], check=True, capture_output=True)
    git(pusher, "checkout", "-q", "-b", "main")
    shutil.copytree(REPO / "data" / "network", pusher / "data" / "network")
    shutil.copytree(REPO / "infra" / "envs", pusher / "infra" / "envs", ignore=shutil.ignore_patterns("*.tfplan", ".terraform*"))
    shutil.copytree(REPO / "agents", pusher / "agents")  # main's own instructions and reply formats
    (pusher / "README.md").write_text("demo\n")
    first = commit_all(pusher, "first")
    git(pusher, "push", "-q", "origin", "main")
    subprocess.run(["git", "clone", "-q", str(origin), str(engineer)], check=True, capture_output=True)
    monkeypatch.setenv("FWAGENT_STATE_DIR", str(tmp_path / "state"))
    return SimpleNamespace(origin=origin, pusher=pusher, engineer=engineer, first=first, tmp=tmp_path)


def push(world, rel, text, message="change"):
    """Change one file on main through the pusher clone; return the new main SHA."""
    path = world.pusher / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    sha = commit_all(world.pusher, message)
    git(world.pusher, "push", "-q", "origin", "main")
    return sha


def ready(world, container, agents=None, now=NOW):
    """Run the sync job's ready step for pusher's HEAD, as sync-network does; return the marker."""
    project = SimpleNamespace(agents=agents if agents is not None else FakeAgents(missing=True))
    return mark_ready(world.pusher, git(world.pusher, "rev-parse", "HEAD").strip(), container, project, "run-1", now)


def settle(agents):
    """Make the versions created so far listed by Foundry, as they are once published."""
    listed = [agents.get_version("x", str(len(agents.versions) + i + 1)) for i in range(len(agents.created))]
    agents.versions, agents.created, agents.missing = agents.versions + listed, [], False


def evaluate(repo, marker):
    """Record the marker's agent definition as evaluated in repo's register, as a reviewed PR would."""
    path = Path(repo) / "agents" / "evaluated-definitions.json"
    data = json.loads(path.read_text())
    data["definitions"][marker["agent"]["definition_sha"]] = {"agent_version": marker["agent"]["version"],
                                                               "evaluation": "validation split, passed"}
    path.write_text(json.dumps(data, indent=2) + "\n")


def no_wait(repo, container, commit, report=print, contents=True):
    """The wait with no waiting: a missing marker stops at once."""
    return snap.wait_for_ready(repo, container, commit, report=report, sync_state=lambda c: None, timeout=0,
                               sleep=lambda s: None, contents=contents)


def agent_for(text):
    """A make_agent that answers text and whose one tool call reads exactly the pinned commit."""
    built = []

    def make(worktree, commit, marker, container):
        built.append((Path(worktree), commit))
        responses = FakeResponses(text, calls=[mcp_call("locate_address_for_env_site", read(commit))])
        return FoundryAgent(SimpleNamespace(), SimpleNamespace(responses=responses), marker["agent"]["version"], commit)
    make.built = built
    return make


STOP = wrapped({"outcome": "stop_and_ask", "reason": "hub_rule", "rules": [], "explanation": "x"})


# ------------------------------------------------------------ missing, incomplete, outdated or mismatched snapshots


def test_a_missing_snapshot_waits_a_bounded_time_with_progress_then_stops(world):
    container, said, slept = FakeContainer(), [], []
    ticks = iter([0, 0, 15, 30])
    with pytest.raises(snap.SyncPending, match="still not ready after 30s. Nothing was drafted") as stopped:
        snap.wait_for_ready(world.engineer, container, world.first, report=said.append, sync_state=lambda c: "running",
                            timeout=30, interval=15, clock=lambda: next(ticks), sleep=slept.append)
    assert slept == [15, 15] and len(said) == 2 and "0s of 30s, sync job running" in said[0]
    assert stopped.value.detail == {"main_commit": world.first, "sync_job": "running", "waited_seconds": 30}


def test_a_snapshot_marked_ready_during_the_wait_is_used(world):
    container = FakeContainer()
    marker = snap.wait_for_ready(world.pusher, container, world.first, report=lambda m: None, sync_state=lambda c: None,
                                 timeout=60, interval=15, clock=iter([0, 0]).__next__,
                                 sleep=lambda s: ready(world, container))
    assert marker["commit"] == world.first and marker["status"] == "ready_for_drafting"


def test_a_failed_sync_stops_at_once_and_never_uses_an_older_snapshot(world):
    container = FakeContainer()
    ready(world, container)  # the first commit is ready
    second = push(world, "infra/envs/dev-eastus2/ip-groups.tfvars", "# newer\n")
    git(world.engineer, "fetch", "-q", "origin", "main")
    with pytest.raises(snap.SyncFailed, match="copying GitHub main to Azure failed.*never used instead"):
        snap.wait_for_ready(world.engineer, container, second, sync_state=lambda c: "failed", sleep=pytest.fail)


BREAKS = {
    "a file missing": (lambda c, sha: c.blobs.pop(f"snapshots/{sha}/data/network/routing.yaml"),
                       "missing data/network/routing.yaml"),
    "an extra file": (lambda c, sha: c.blobs.update({f"snapshots/{sha}/infra/envs/stray.tfvars": b"x"}),
                      "extra infra/envs/stray.tfvars"),
    "changed bytes": (lambda c, sha: c.blobs.update({f"snapshots/{sha}/data/network/routing.yaml": b"tampered"}),
                      "changed data/network/routing.yaml"),
    "marker files differ from git": (lambda c, sha: c.blobs.update({f"ready/{sha}.json": json.dumps(
        {**json.loads(c.blobs[f"ready/{sha}.json"]), "files": {"data/network/routing.yaml": "0" * 64}}).encode()}),
        "differing"),
    "marker names another commit": (lambda c, sha: c.blobs.update({f"ready/{sha}.json": json.dumps(
        {**json.loads(c.blobs[f"ready/{sha}.json"]), "commit": "e" * 40}).encode()}), "marker_commit"),
}


@pytest.mark.parametrize("break_it, why", BREAKS.values(), ids=BREAKS.keys())
def test_an_incomplete_or_mismatched_snapshot_stops_before_any_agent_is_built(world, break_it, why):
    container = FakeContainer()
    ready(world, container)
    break_it(container, world.first)
    make = agent_for(STOP)
    with pytest.raises(snap.SnapshotMismatch) as stopped:
        draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {}, {}, make, container, report=lambda m: None,
                        wait=no_wait)
    assert why in json.dumps(stopped.value.detail) and stopped.value.detail["main_commit"] == world.first
    assert make.built == [] and git(world.engineer, "branch", "--list", "agent/*") == ""


def test_an_outdated_snapshot_is_never_used_for_a_newer_main(world):
    container = FakeContainer()
    ready(world, container)  # only the older commit is ready
    push(world, "infra/envs/dev-eastus2/ip-groups.tfvars", "# newer\n")
    make = agent_for(STOP)
    with pytest.raises(snap.SyncPending, match="still not ready"):
        draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {}, {}, make, container, report=lambda m: None,
                        wait=no_wait)
    assert make.built == []


# ------------------------------------------------------------ the sync job: immutable snapshots, reused agent versions


def test_routine_policy_merges_and_docs_only_commits_reuse_the_same_agent_version(world):
    container, agents = FakeContainer(), FakeAgents(missing=True)
    first = ready(world, container, agents)
    push(world, "infra/envs/dev-eastus2/firewall_policy_rule_collection_groups/sett.tfvars",
         (world.pusher / "infra/envs/dev-eastus2/firewall_policy_rule_collection_groups/sett.tfvars").read_text() + "# merged rule\n")
    settle(agents)  # what Foundry now lists
    policy = ready(world, container, agents)
    push(world, "README.md", "docs only\n")
    docs = ready(world, container, agents)
    assert first["agent"]["version"] == policy["agent"]["version"] == docs["agent"]["version"] == "1"
    assert agents.created == []  # no new version for new network data or docs
    assert len({first["commit"], policy["commit"], docs["commit"]}) == 3  # every main commit has its own marker
    assert policy["files"] != first["files"] and docs["files"] == policy["files"]


def test_a_change_to_the_instructions_publishes_a_new_version(world):
    container, agents = FakeContainer(), FakeAgents(missing=True)
    ready(world, container, agents)
    settle(agents)
    push(world, "data/standards/collections.md", "# a new standard page\n")
    assert ready(world, container, agents)["agent"]["version"] == "2" and len(agents.created) == 1


def test_a_snapshot_file_is_never_overwritten_with_other_bytes(world):
    container = FakeContainer()
    files = snap.commit_files(world.pusher, world.first)
    container.upload_blob(f"snapshots/{world.first}/data/network/routing.yaml", b"other bytes")
    with pytest.raises(snap.SnapshotMismatch, match="already holds other bytes.*never overwritten"):
        snap.upload_snapshot(container, world.first, files)


def test_a_ready_marker_is_written_once_and_a_second_run_changes_nothing(world):
    container = FakeContainer()
    marker = ready(world, container)
    stored = container.blobs[f"ready/{world.first}.json"]
    assert ready(world, container, now=NOW + timedelta(hours=1)) == marker and container.blobs[f"ready/{world.first}.json"] == stored
    with pytest.raises(snap.SnapshotMismatch, match="different ready marker"):
        snap.write_marker(container, {**marker, "agent": {**marker["agent"], "version": "99"}})


def test_a_failed_agent_check_leaves_no_marker(world):
    container, agents = FakeContainer(), FakeAgents(missing=True)
    agents.get_version = lambda name, version: SimpleNamespace(
        metadata={"definition_sha": "0"}, definition={"tools": [{"headers": {}}], "structured_inputs": {}})
    with pytest.raises(AgentError, match="does not match"):
        ready(world, container, agents)
    assert not [n for n in container.blobs if n.startswith("ready/")]


def test_the_sync_step_refuses_a_checkout_at_another_commit(world):
    second = push(world, "README.md", "newer\n")
    git(world.pusher, "checkout", "-q", world.first)
    with pytest.raises(AgentError, match="not at"):
        mark_ready(world.pusher, second, FakeContainer(), SimpleNamespace(agents=FakeAgents(missing=True)))


def test_a_replaced_snapshot_is_kept_for_the_grace_period_and_the_newest_never_deleted(world):
    container = FakeContainer()
    ready(world, container, now=NOW - timedelta(hours=50))
    old_replaced = push(world, "README.md", "b\n")
    ready(world, container, now=NOW - timedelta(hours=30))  # replaced first: 30h ago
    recent = push(world, "README.md", "c\n")
    ready(world, container, now=NOW - timedelta(hours=25))  # replaced old_replaced 25h ago
    newest = push(world, "README.md", "d\n")
    ready(world, container, now=NOW - timedelta(hours=1))  # replaced recent 1h ago: a run may still hold it
    deleted = snap.prune(container, keep=newest, now=NOW)
    assert deleted == sorted([world.first, old_replaced])
    left = {n.split("/")[1] for n in container.blobs if n.startswith("snapshots/")}
    assert left == {recent, newest}
    assert len([n for n in container.blobs if n.startswith("ready/")]) == 4  # markers are kept for the audit


def test_no_run_can_outlive_its_snapshot():
    assert snap.GRACE > snap.RUN_DEADLINE * 10


# ------------------------------------------------------------ drafting from the latest main


def test_the_draft_branches_from_the_latest_origin_main_even_when_the_local_checkout_is_behind(world):
    container = FakeContainer()
    head = push(world, "infra/envs/dev-eastus2/ip-groups.tfvars", "# newer\n")
    ready(world, container)
    assert git(world.engineer, "rev-parse", "HEAD").strip() == world.first  # the engineer never pulled
    make = agent_for(STOP)
    draft = draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {}, make,
                            container, report=lambda m: None, wait=no_wait)
    assert draft.commit == head and make.built == [(draft.worktree, head)]
    assert git(draft.worktree, "rev-parse", "HEAD").strip() == head and draft.branch == f"agent/RITM0011001-{head[:7]}"
    attempt = draft.audit["attempts"][0]
    assert (attempt["main_commit"], attempt["snapshot"], attempt["agent_version"], attempt["tool_commits"]) == (
        head, head, "1", [head])
    assert attempt["marker"]["checks"]["bytes_match_git"] is True and attempt["marker"]["checks"]["files"] > 50


def test_a_relevant_change_on_main_during_the_draft_regenerates_from_the_new_main(world):
    container = FakeContainer()
    ready(world, container)
    calls = []

    def make(worktree, commit, marker, container_):
        calls.append(commit)
        if len(calls) == 1:  # a policy merge lands while the first draft runs
            push(world, "infra/envs/dev-eastus2/ip-groups.tfvars", "# merged meanwhile\n")
            ready(world, container)
        return agent_for(STOP)(worktree, commit, marker, container_)
    draft = draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {}, make,
                            container, report=lambda m: None, wait=no_wait)
    second = git(world.pusher, "rev-parse", "HEAD").strip()
    assert calls == [world.first, second] and draft.commit == second
    assert [a["main_commit"] for a in draft.audit["attempts"]] == [world.first, second]
    assert draft.audit["attempts"][0]["relevant_changes"] == ["infra/envs/dev-eastus2/ip-groups.tfvars"]
    assert git(world.engineer, "for-each-ref", "--format=%(refname:short)", "refs/heads/agent/").split() == [f"agent/RITM0011001-{second[:7]}"]


def test_a_docs_only_change_on_main_keeps_the_draft(world):
    container = FakeContainer()
    ready(world, container)

    def make(worktree, commit, marker, container_):
        push(world, "README.md", "docs only\n")
        return agent_for(STOP)(worktree, commit, marker, container_)
    draft = draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {}, make,
                            container, report=lambda m: None, wait=no_wait)
    assert draft.commit == world.first and len(draft.audit["attempts"]) == 1


def test_main_that_keeps_moving_stops_after_bounded_retries_and_leaves_no_branch(world):
    container = FakeContainer()
    ready(world, container)
    n = iter(range(100))

    def make(worktree, commit, marker, container_):
        push(world, "infra/envs/dev-eastus2/ip-groups.tfvars", f"# {next(n)}\n")
        ready(world, container)
        return agent_for(STOP)(worktree, commit, marker, container_)
    with pytest.raises(MainMoving, match="each of 3 attempts"):
        draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {}, make,
                        container, report=lambda m: None, wait=no_wait)
    assert git(world.engineer, "branch", "--list", "agent/*") == ""


def test_a_cancelled_sync_moves_on_to_the_newer_main(world):
    container = FakeContainer()
    first_seen = []

    def wait(repo, container_, commit, report=print, **options):
        if not first_seen:
            first_seen.append(commit)
            push(world, "README.md", "newer\n")  # the push whose sync replaced this one
            ready(world, container)
            raise snap.SyncSuperseded("cancelled")
        return no_wait(repo, container_, commit, **options)
    draft = draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {},
                            agent_for(STOP), container, report=lambda m: None, wait=wait)
    assert first_seen == [world.first] and draft.commit == git(world.pusher, "rev-parse", "HEAD").strip()


def test_a_run_past_its_deadline_is_thrown_away(world):
    container = FakeContainer()
    ready(world, container)
    ticks = iter([0, snap.RUN_DEADLINE.total_seconds() + 1])
    with pytest.raises(RunTooLong):
        draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {},
                        agent_for(STOP), container, report=lambda m: None, wait=no_wait, clock=lambda: next(ticks))
    assert git(world.engineer, "branch", "--list", "agent/*") == ""


def test_tool_answers_from_another_revision_stop_the_draft_and_remove_its_branch(world):
    container = FakeContainer()
    ready(world, container)

    def make(worktree, commit, marker, container_):
        responses = FakeResponses(STOP, calls=[mcp_call("duplicate_rule_check", read("d" * 40))])
        return FoundryAgent(SimpleNamespace(), SimpleNamespace(responses=responses), "1", commit)
    with pytest.raises(AgentError, match="not all from snapshot"):
        draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {}, make,
                        container, report=lambda m: None, wait=no_wait)
    assert git(world.engineer, "branch", "--list", "agent/*") == ""


# ------------------------------------------------------------ the pinned agent: chosen by the marker, never published


@pytest.fixture
def endpoint(monkeypatch):
    monkeypatch.setenv("FWAGENT_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")


def test_the_pinned_agent_uses_the_markers_version_and_never_publishes(world, endpoint, monkeypatch):
    container, agents = FakeContainer(), FakeAgents(missing=True)
    marker = ready(world, container, agents)
    settle(agents)
    project = SimpleNamespace(agents=agents, get_openai_client=lambda **o: SimpleNamespace(options=o))
    monkeypatch.setattr("workflow.agent.connect", lambda e: project)
    evaluate(world.pusher, marker)
    a = FoundryAgent.pinned(world.pusher, world.first, marker, container)
    assert (a.version, a.snapshot, a.marker) == ("1", world.first, marker) and agents.created == []


def test_the_pinned_agent_stops_when_mains_instructions_differ_from_the_ready_version(world, endpoint, monkeypatch):
    container = FakeContainer()
    marker = ready(world, container)
    monkeypatch.setattr("workflow.agent.connect", lambda e: pytest.fail("Foundry must not be called"))
    (world.pusher / "data/standards").mkdir(parents=True, exist_ok=True)
    (world.pusher / "data/standards/extra.md").write_text("# not yet published\n")
    with pytest.raises(AgentError, match="does not match GitHub main's instructions, model or tools") as stopped:
        FoundryAgent.pinned(world.pusher, world.first, marker, container)
    assert stopped.value.detail["ready_version"] == "1" and stopped.value.detail["main_commit"] == world.first


def test_the_pinned_agent_stops_when_the_branch_files_differ_from_the_snapshot(world, endpoint):
    container = FakeContainer()
    marker = ready(world, container)
    (world.pusher / "data/network/routing.yaml").write_text("edited\n")
    with pytest.raises(AgentError, match="ticket branch's files differ from GitHub main") as stopped:
        FoundryAgent.pinned(world.pusher, world.first, marker, container)
    assert stopped.value.detail["differing"] == ["data/network/routing.yaml"]


def test_every_request_supplies_the_pinned_commit_as_the_snapshot_input(world):
    responses = FakeResponses(STOP, calls=[mcp_call("resolve_env_site", read(world.first))])
    FoundryAgent(SimpleNamespace(), SimpleNamespace(responses=responses), "1", world.first)({"number": "RITM0011001"})
    assert responses.requests[0]["extra_body"]["structured_inputs"] == {"snapshot": world.first}


def test_the_eval_runner_pin_needs_a_ready_marker_and_never_publishes(world, endpoint, monkeypatch):
    monkeypatch.delenv("FWAGENT_SNAPSHOT_COMMIT", raising=False)
    monkeypatch.setattr("workflow.agent.connect", lambda e: pytest.fail("Foundry must not be called"))
    with pytest.raises(snap.SyncPending, match="no snapshot ready for drafting"):
        FoundryAgent.from_env(world.pusher, container=FakeContainer())


# ------------------------------------------------------------ through fwagent: acceptance kept, drafts on a branch


def _submit_and_accept(world, number="RITM0011001"):
    """Submit one validation ticket in the engineer's repo and accept its exact version."""
    data = yaml.safe_load((REQUESTS / "validation" / f"validation_{number}.yaml").read_text())
    path = world.tmp / f"{number}.yaml"
    path.write_text(yaml.safe_dump(data["ticket"]))
    assert cli.main(["submit", str(path)], repo=world.engineer) == cli.REVIEW
    version = cli.load_record(world.engineer, number)["ticket_version"][:12]
    code = cli.main(["accept", number, "--ticket-version", version, "--engineer", "rbpal", "--reason", "checked"],
                    repo=world.engineer)
    return data, code


@pytest.fixture
def live(world, endpoint, monkeypatch):
    """fwagent with a fake container, no wait, and a fake drafter answering the ticket's labelled reply."""
    container = FakeContainer()
    monkeypatch.setattr(cli, "snapshot_container", lambda: container)
    monkeypatch.setattr(cli, "draft_from_main", lambda *a, **k: draft_from_main(*a, **{**k, "wait": no_wait,
                                                                                    "report": lambda m: None}))
    data = yaml.safe_load((REQUESTS / "validation" / "validation_RITM0011001.yaml").read_text())
    reply = {k: copy.deepcopy(data["expected"][k]) for k in ("outcome", "reason", "rules") if k in data["expected"]}
    make = agent_for(wrapped({**reply, "explanation": "Drafted for both selected sites."}))
    monkeypatch.setattr(cli, "live_agent", make)
    return SimpleNamespace(container=container, make=make)


def test_accept_drafts_on_a_branch_from_main_and_records_the_audit(world, live):
    ready(world, live.container)
    _, code = _submit_and_accept(world)
    record = cli.load_record(world.engineer, "RITM0011001")
    assert code == cli.DONE and record["status"] == "drafted" and len(record["files"]) == 2
    assert record["branch"] == f"agent/RITM0011001-{world.first[:7]}"
    assert record["drafting"]["main_commit"] == record["drafting"]["snapshot"] == world.first
    assert record["drafting"]["agent_version"] == "1"
    assert git(world.engineer, "status", "--porcelain") == ""  # the engineer's own checkout is untouched
    changed = git(record["worktree"], "status", "--porcelain").split()
    assert len([p for p in changed if p.endswith(".tfvars")]) == 2  # the draft sits on the ticket branch


def test_a_sync_delay_keeps_the_acceptance_and_draft_finishes_later_without_a_new_accept(world, live, capsys):
    _, code = _submit_and_accept(world)  # nothing is ready yet
    record = cli.load_record(world.engineer, "RITM0011001")
    assert code == cli.REFUSED and record["status"] == "accepted" and live.make.built == []
    assert "Your acceptance is kept" in capsys.readouterr().out
    ready(world, live.container)  # the sync job finishes
    assert cli.main(["draft", "RITM0011001"], repo=world.engineer) == cli.DONE
    record = cli.load_record(world.engineer, "RITM0011001")
    assert record["status"] == "drafted" and [h["action"] for h in record["history"]].count("accept") == 1


def test_an_edited_ticket_needs_a_new_acceptance_before_any_draft(world, live, capsys):
    data, _ = _submit_and_accept(world)  # sync pending: accepted, not drafted
    edited = copy.deepcopy(data["ticket"])
    edited["justification"] = edited.get("justification", "") + " Updated by the requester."
    path = world.tmp / "edited.yaml"
    path.write_text(yaml.safe_dump(edited))
    cli.main(["edit", "RITM0011001", str(path), "--engineer", "rbpal", "--note", "requester update"], repo=world.engineer)
    ready(world, live.container)
    assert cli.main(["draft", "RITM0011001"], repo=world.engineer) == cli.REFUSED
    assert "accept it first" in capsys.readouterr().out and live.make.built == []


def test_the_acceptance_is_saved_before_drafting_starts_so_a_crash_cannot_lose_it(world, live, monkeypatch):
    def crash(*args, **kwargs):
        """Drafting dies at once, as on Ctrl-C, before any error handling runs."""
        raise KeyboardInterrupt
    monkeypatch.setattr(cli, "draft_from_main", crash)
    with pytest.raises(KeyboardInterrupt):
        _submit_and_accept(world)
    record = cli.load_record(world.engineer, "RITM0011001")
    assert record["status"] == "accepted" and record["review"]["ticket_version"] == record["ticket_version"]


# ------------------------------------------------------------ the pre-call check: branch, Azure and main must match

import re  # noqa: E402

import workflow.mainline as mainline  # noqa: E402

HEX_ID = re.compile(r"\b[0-9a-f]{7,40}\b")  # a commit or hash; the engineer's messages must hold none


def tamper_after_branching(monkeypatch, change):
    """Run change(worktree, commit) right after the ticket branch is made, before the pre-call check."""
    real = mainline.add_branch

    def add_branch(repo, worktrees, number, commit):
        branch, path = real(repo, worktrees, number, commit)
        change(path, commit)
        return branch, path
    monkeypatch.setattr(mainline, "add_branch", add_branch)


def blocked(world, container, said=None, kept=False):
    """Draft once and return the PreflightFailed it raises; the agent is never built; the branch stays only if edited."""
    make = agent_for(STOP)
    with pytest.raises(mainline.PreflightFailed) as stopped:
        draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {}, make,
                        container, report=(said.append if said is not None else lambda m: None), wait=no_wait)
    assert make.built == []
    assert (git(world.engineer, "branch", "--list", "agent/*") != "") is kept
    assert not HEX_ID.search(str(stopped.value))  # a plain message; the IDs are in .detail
    return stopped.value


def rewrite_marker(container, sha, **fields):
    """Replace fields in the ready record of commit sha in Azure."""
    name = f"ready/{sha}.json"
    container.blobs[name] = json.dumps({**json.loads(container.blobs[name]), **fields}).encode()


ROUTING = "data/network/routing.yaml"
MISMATCHES = {
    "branch file edited": (lambda w, c, box: (w / ROUTING).write_text("edited on the branch\n"),
                           "branch_files_match_main", "1 file(s) on the ticket branch differ from GitHub main"),
    "branch file deleted": (lambda w, c, box: (w / ROUTING).unlink(),
                            "branch_files_match_main", "1 file(s) on the ticket branch differ"),
    "untracked file on the branch": (lambda w, c, box: (w / "infra/envs/dev-eastus2/stray.tfvars").write_text("x\n"),
                                     "branch_files_match_main", "1 file(s) on the ticket branch differ"),
    "Azure file changed": (lambda w, c, box: box.blobs.update({f"snapshots/{c}/{ROUTING}": b"tampered"}),
                           "azure_files_match_main", "Azure's copy of GitHub main differs in 1 file(s)"),
    "Azure file missing": (lambda w, c, box: box.blobs.pop(f"snapshots/{c}/{ROUTING}"),
                           "azure_files_match_main", "Azure's copy of GitHub main differs in 1 file(s)"),
    "Azure extra file": (lambda w, c, box: box.blobs.update({f"snapshots/{c}/infra/envs/stray.tfvars": b"x"}),
                         "azure_files_match_main", "differs in 1 file(s)"),
    "ready record for another commit": (lambda w, c, box: rewrite_marker(box, c, commit="e" * 40),
                                        "ready_record_is_for_main", "ready record belongs to a different version"),
    "ready record lists other files": (lambda w, c, box: rewrite_marker(box, c, files={ROUTING: "0" * 64}),
                                       "ready_record_files_match_main", "ready record lists different files"),
}


MISMATCHES["ready record removed"] = (lambda w, c, box: box.blobs.pop(f"ready/{c}.json"),
                                     "ready_record_is_for_main", "ready record belongs to a different version")
MISMATCHES["ready record rewritten, files intact"] = (lambda w, c, box: rewrite_marker(box, c, deploy_run="run-2"),
                                                     "ready_record_unchanged", "ready record changed after the run started")


@pytest.mark.parametrize("change, check, message", MISMATCHES.values(), ids=MISMATCHES.keys())
def test_a_mismatch_found_right_before_the_call_blocks_the_draft(world, monkeypatch, change, check, message):
    container = FakeContainer()
    ready(world, container)  # the wait passes: everything matched a moment ago
    tamper_after_branching(monkeypatch, lambda w, c: change(w, c, container))
    edits_branch = check == "branch_files_match_main"  # someone else's change on the branch: kept, never deleted
    error = blocked(world, container, kept=edits_branch)
    assert ("kept_worktree" in error.detail) is edits_branch
    assert str(error).startswith("Check failed: ") and message in str(error)
    assert str(error).endswith("Nothing was sent to the agent")
    failed = [k for k, ok in error.detail["checks"].items() if not ok]
    assert failed[0] == check and error.detail["passed"] is False
    assert error.detail["main_commit"] == world.first  # the IDs are kept for the audit record


def test_a_branch_at_another_commit_is_blocked_even_when_its_files_match(world, monkeypatch):
    container = FakeContainer()
    second = push(world, "README.md", "docs only\n")  # same data files, different commit
    ready(world, container)
    tamper_after_branching(monkeypatch, lambda w, c: git(w, "reset", "-q", "--hard", world.first))
    error = blocked(world, container)  # moved but unedited and with no new commits: removed
    assert "does not start from the latest GitHub main" in str(error)
    assert (error.detail["branch_commit"], error.detail["main_commit"]) == (world.first, second)
    assert error.detail["checks"]["branch_files_match_main"] is True  # the commit ID alone caught it


def test_main_moving_after_branching_starts_again_from_the_new_main(world, monkeypatch):
    container = FakeContainer()
    ready(world, container)
    moved = []

    def move_once(w, c):
        if not moved:
            moved.append(push(world, "README.md", "newer\n"))
            ready(world, container)
    tamper_after_branching(monkeypatch, move_once)
    draft = draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {},
                            agent_for(STOP), container, report=lambda m: None, wait=no_wait)
    first, second = draft.audit["attempts"]
    assert first["restarted"] == "main moved before the agent call" and first["preflight"]["latest_main"] == moved[0]
    assert draft.commit == moved[0] and second["preflight"]["passed"] is True


def test_a_passed_check_tells_the_engineer_plainly_and_records_every_id(world):
    container, said = FakeContainer(), []
    ready(world, container)
    draft = draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {},
                            agent_for(STOP), container, report=said.append, wait=no_wait)
    check = draft.audit["attempts"][0]["preflight"]
    assert check["passed"] is True and all(check["checks"].values())
    assert check["main_commit"] == check["latest_main"] == check["branch_commit"] == check["ready_record_commit"] == world.first
    assert len(check["manifest_sha256"]) == 64 and check["branch_differences"] == [] and check["azure_problems"] == []
    assert any(m.startswith("Check passed: the ticket branch, Azure's copy and GitHub main match") for m in said)
    assert not any(HEX_ID.search(m) for m in said)  # no commit IDs on screen


def test_fwagent_shows_a_plain_failure_and_keeps_the_ids_in_the_audit_log(world, live, monkeypatch, capsys):
    ready(world, live.container)
    tamper_after_branching(monkeypatch, lambda w, c: (w / ROUTING).write_text("edited\n"))
    _, code = _submit_and_accept(world)
    out = capsys.readouterr().out
    assert code == cli.REFUSED and "Check failed: 1 file(s) on the ticket branch differ from GitHub main" in out
    assert not HEX_ID.search(out.split("refused:")[-1])
    stopped = cli.load_record(world.engineer, "RITM0011001")["history"][-1]
    assert stopped["action"] == "draft_stopped" and stopped["detail"]["main_commit"] == world.first
    assert stopped["detail"]["branch_differences"] == [ROUTING] and live.make.built == []


def test_fwagent_records_the_passed_check_in_the_draft_audit(world, live):
    ready(world, live.container)
    _submit_and_accept(world)
    record = cli.load_record(world.engineer, "RITM0011001")
    check = record["history"][-1]["attempts"][0]["preflight"]
    assert record["status"] == "drafted" and check["passed"] is True and check["branch_commit"] == world.first



# ------------------------------------------------------------ main's instructions, the evaluation gate, safe cleanup

from workflow.agent import NotEvaluated, instructions  # noqa: E402


@pytest.fixture
def foundry_project(endpoint, monkeypatch):
    """A fake Foundry project the pinned agent connects to; it lists whatever the sync job published."""
    agents = FakeAgents(missing=True)
    project = SimpleNamespace(agents=agents, get_openai_client=lambda **o: SimpleNamespace(options=o))
    monkeypatch.setattr("workflow.agent.connect", lambda e: project)
    return agents


def test_the_definition_comes_from_mains_files_not_from_this_macs_code(world, foundry_project):
    container = FakeContainer()
    push(world, "agents/drafter.md", (REPO / "agents/drafter.md").read_text() + "\nA rule merged on main.\n")
    marker = ready(world, container, foundry_project)  # published from main's drafter.md
    settle(foundry_project)
    evaluate(world.pusher, marker)
    assert "A rule merged on main." in instructions(world.pusher)
    assert "A rule merged on main." not in (REPO / "agents/drafter.md").read_text()  # this Mac's copy is older
    a = FoundryAgent.pinned(world.pusher, marker["commit"], marker, container)
    assert a.version == marker["agent"]["version"]


def test_older_reply_checks_on_this_mac_block_the_draft_with_a_plain_message(world, foundry_project):
    container = FakeContainer()
    schema = json.loads((REPO / "agents/reply.schema.json").read_text())
    push(world, "agents/reply.schema.json", json.dumps({**schema, "description": "changed on main"}, indent=2))
    marker = ready(world, container, foundry_project)
    with pytest.raises(AgentError, match="Pull main and try again") as stopped:
        FoundryAgent.pinned(world.pusher, marker["commit"], marker, container)
    assert stopped.value.detail["differing"] == ["agents/reply.schema.json"]


def test_an_unevaluated_definition_is_blocked_before_any_foundry_call(world, endpoint, monkeypatch):
    container = FakeContainer()
    marker = ready(world, container)
    monkeypatch.setattr("workflow.agent.connect", lambda e: pytest.fail("Foundry must not be called"))
    with pytest.raises(NotEvaluated, match="has not passed its evaluation") as stopped:
        FoundryAgent.pinned(world.pusher, world.first, marker, container)
    assert not HEX_ID.search(str(stopped.value))
    assert stopped.value.detail["definition_sha"] == marker["agent"]["definition_sha"]
    assert stopped.value.detail["register"] == "agents/evaluated-definitions.json"


def test_an_entry_for_another_definition_does_not_open_the_gate(world, endpoint, monkeypatch):
    container = FakeContainer()
    marker = ready(world, container)
    evaluate(world.pusher, {"agent": {"definition_sha": "0" * 16, "version": "9"}})  # an older, evaluated definition
    monkeypatch.setattr("workflow.agent.connect", lambda e: pytest.fail("Foundry must not be called"))
    with pytest.raises(NotEvaluated):
        FoundryAgent.pinned(world.pusher, world.first, marker, container)


def test_the_eval_runner_may_use_an_unevaluated_definition_since_it_is_how_one_gets_evaluated(world, foundry_project, monkeypatch):
    container = FakeContainer()
    marker = ready(world, container, foundry_project)
    settle(foundry_project)
    git(world.pusher, "checkout", "-q", world.first)
    monkeypatch.delenv("FWAGENT_SNAPSHOT_COMMIT", raising=False)
    assert FoundryAgent.from_env(world.pusher, container=container).version == marker["agent"]["version"]


def test_every_real_register_entry_names_a_definition_hash_and_its_passed_evaluation():
    entries = json.loads((REPO / "agents/evaluated-definitions.json").read_text())["definitions"]
    for sha, entry in entries.items():
        assert re.fullmatch(r"[0-9a-f]{16}", sha), sha
        assert entry["evaluation"] == "validation split, passed", sha
        assert re.fullmatch(r"\d+", entry["agent_version"]), sha
        assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", entry["evaluated_on"]), sha
        assert re.fullmatch(r"[0-9a-f]{40}", entry["main_commit"]), sha


def test_fwagent_blocks_an_unevaluated_agent_plainly_and_audits_it(world, live, foundry_project, monkeypatch, capsys):
    ready(world, live.container, foundry_project)
    settle(foundry_project)
    monkeypatch.setattr(cli, "live_agent", REAL_LIVE_AGENT)  # the real pinned agent, gate included
    _, code = _submit_and_accept(world)
    out = capsys.readouterr().out.split("refused:")[-1]
    assert code == cli.REFUSED and "has not passed its evaluation" in out and not HEX_ID.search(out)
    record = cli.load_record(world.engineer, "RITM0011001")
    assert record["status"] == "accepted" and "definition_sha" in record["history"][-1]["detail"]
    assert git(world.engineer, "branch", "--list", "agent/*") == ""  # an unedited branch is removed


def test_regeneration_keeps_a_branch_the_engineer_edited_and_drafts_on_a_new_one(world, monkeypatch):
    container = FakeContainer()
    ready(world, container)
    calls = []

    def make(worktree, commit, marker, container_):
        calls.append(worktree)
        if len(calls) == 1:
            (Path(worktree) / "notes.txt").write_text("my notes\n")  # the engineer works in the branch meanwhile
            push(world, "infra/envs/dev-eastus2/ip-groups.tfvars", "# merged meanwhile\n")
            ready(world, container)
        return agent_for(STOP)(worktree, commit, marker, container_)
    draft = draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {}, make,
                            container, report=lambda m: None, wait=no_wait)
    assert (calls[0] / "notes.txt").read_text() == "my notes\n"  # kept, untouched
    assert {"kept_branch": f"agent/RITM0011001-{world.first[:7]}", "kept_worktree": str(calls[0])} in draft.audit["attempts"]
    assert len(git(world.engineer, "for-each-ref", "--format=%(refname:short)", "refs/heads/agent/").split()) == 2


def test_cleanup_keeps_a_branch_with_a_commit_the_run_did_not_make(world, monkeypatch):
    container = FakeContainer()
    ready(world, container)

    def commit_then_fail(worktree, commit, marker, container_):
        (Path(worktree) / "notes.txt").write_text("x\n")
        commit_all(Path(worktree), "engineer's commit")
        raise AgentError("the agent call failed")
    with pytest.raises(AgentError) as stopped:
        draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {},
                        commit_then_fail, container, report=lambda m: None, wait=no_wait)
    assert stopped.value.detail["kept_branch"] == f"agent/RITM0011001-{world.first[:7]}"
    assert "engineer's commit" in git(world.engineer, "log", "-1", "--format=%s", stopped.value.detail["kept_branch"])


def test_a_ticket_that_ends_without_a_draft_leaves_no_branch(world, live, monkeypatch):
    ready(world, live.container)
    monkeypatch.setattr(cli, "live_agent", agent_for(STOP))
    _submit_and_accept(world)
    record = cli.load_record(world.engineer, "RITM0011001")
    assert record["status"] == "awaiting_review" and not record.get("worktree")
    assert git(world.engineer, "branch", "--list", "agent/*") == ""



# ------------------------------------------------------------ one byte check per draft; the register is not the definition


def test_a_draft_downloads_each_snapshot_file_once_right_before_the_call(world):
    container = FakeContainer()
    ready(world, container)
    container.downloads = []
    draft_from_main(world.engineer, world.tmp / "wt", "RITM0011001", {"number": "RITM0011001"}, {}, agent_for(STOP),
                    container, report=lambda m: None, wait=no_wait)
    files = [n for n in container.downloads if n.startswith("snapshots/")]
    wanted = snap.commit_files(world.pusher, world.first)
    assert len(files) == len(set(files)) == len(wanted)  # every file once: the wait checks only the record and the list


def test_the_eval_runner_and_the_sync_check_still_check_every_byte(world):
    container = FakeContainer()
    ready(world, container)
    container.blobs[f"snapshots/{world.first}/{ROUTING}"] = b"tampered"
    with pytest.raises(snap.SnapshotMismatch):
        snap.verify_ready(world.pusher, container, world.first)  # contents=True is the default
    assert snap.verify_ready(world.pusher, container, world.first, contents=False)["commit"] == world.first


def test_an_evaluation_register_entry_does_not_change_the_agent_definition_hash(world):
    container, agents = FakeContainer(), FakeAgents(missing=True)
    marker = ready(world, container, agents)
    before = definition_sha(local_definition(world.pusher))
    evaluate(world.pusher, marker)  # the reviewed entry, committed and pushed as its own change to main
    commit_all(world.pusher, "Record the passed evaluation")
    git(world.pusher, "push", "-q", "origin", "main")
    assert definition_sha(local_definition(world.pusher)) == before == marker["agent"]["definition_sha"]
    settle(agents)
    after = ready(world, container, agents)
    assert after["agent"]["version"] == marker["agent"]["version"] and agents.created == []  # no new version
