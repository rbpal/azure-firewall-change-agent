"""Draft one accepted ticket from the latest GitHub main, with every tool reading that same revision.

Example: main is at 4f2a1c9…. draft_from_main fetches origin/main, waits until the sync job has
marked 4f2a1c9… ready, makes branch agent/RITM0013002-4f2a1c9 in its own worktree, and calls the
agent pinned to 4f2a1c9…. Before it returns, it fetches main again. If main moved and changed the
network data, the rule files or the agent's instructions, it throws that reply away and drafts
again from the new main, up to MAX_ATTEMPTS times.

Why: main is the source of truth. The engineer never types a commit or picks an agent version;
the commit comes from GitHub and the version from that commit's ready marker.

Right before every agent call, preflight checks that the ticket branch, Azure's copy and the latest
GitHub main are the same commit and hold the same file bytes. A mismatch sends nothing to the agent.
The engineer sees one plain line; the commits and file hashes go to the audit record.

Safety rule: an attempt writes nothing to the repo the engineer works in. It only adds a branch
and a worktree, and removes both when the attempt fails or is thrown away. A run that outlives
RUN_DEADLINE is thrown away, because its snapshot is only promised for that long.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from workflow.agent import DATA, GUIDANCE, AgentError
from workflow.snapshot import (RUN_DEADLINE, SnapshotMismatch, SyncSuperseded, blob_problems, commit_files, differing,
                               disk_manifest, git, manifest, read_marker, wait_for_ready)

MAX_ATTEMPTS = 3
RELEVANT = (*DATA, *GUIDANCE, "agents")  # a change here makes a draft from the older main stale


class MainMoving(AgentError):
    """Main kept changing relevant files while the agent drafted; nothing was kept."""


class PreflightFailed(SnapshotMismatch):
    """The ticket branch, Azure's copy or GitHub main did not match right before the agent call; nothing was sent."""


FAILURES = {  # the first failing check decides the engineer's one-line message
    "branch_starts_at_main": "the ticket branch does not start from the latest GitHub main",
    "branch_files_match_main": "{n} file(s) on the ticket branch differ from GitHub main",
    "ready_record_is_for_main": "Azure's ready record belongs to a different version of GitHub main",
    "ready_record_files_match_main": "Azure's ready record lists different files from GitHub main",
    "ready_record_unchanged": "Azure's ready record changed after the run started",
    "azure_files_match_main": "Azure's copy of GitHub main differs in {n} file(s)",
}


class RunTooLong(AgentError):
    """The attempt ran past RUN_DEADLINE; its snapshot is no longer promised, so the reply was thrown away."""


@dataclass
class Draft:
    """One reply drafted from one main commit, with the branch that holds it and the audit trail."""
    reply: dict
    commit: str
    branch: str
    worktree: Path
    audit: dict = field(default_factory=dict)


def remote() -> str:
    """The Git remote that holds main; origin unless FWAGENT_MAIN_REMOTE says otherwise."""
    return os.environ.get("FWAGENT_MAIN_REMOTE", "origin")


def fetch_main(repo: Path) -> str:
    """Fetch main from the remote and return its full commit SHA."""
    git(repo, "fetch", "--quiet", remote(), "main")
    return git(repo, "rev-parse", f"refs/remotes/{remote()}/main").strip()


def relevant_changes(repo: Path, before: str, after: str) -> list[str]:
    """Files that changed between two main commits and could change the draft: data, rules or instructions."""
    if before == after:
        return []
    return [line for line in git(repo, "diff", "--name-only", before, after, "--", *RELEVANT).splitlines() if line]


def add_branch(repo: Path, worktrees: Path, number: str, commit: str) -> tuple[str, Path]:
    """Create branch agent/<ticket>-<commit> in a new worktree at commit; refuse if it already exists."""
    branch, path = f"agent/{number}-{commit[:7]}", worktrees / f"{number}-{commit[:7]}"
    if path.exists():
        raise AgentError(f"{path} already exists: this ticket was already drafted from main {commit[:12]}. "
                         "Review that draft, or remove the worktree and its branch first")
    path.parent.mkdir(parents=True, exist_ok=True)
    git(repo, "worktree", "add", "--quiet", "-b", branch, str(path), commit)
    return branch, path


def remove_branch(repo: Path, branch: str, path: Path) -> None:
    """Remove a worktree and its branch that this run created."""
    git(repo, "worktree", "remove", "--force", str(path))
    git(repo, "branch", "-D", branch)


def preflight(repo: Path, worktree: Path, container, commit: str, marker: dict) -> dict:
    """Compare the ticket branch, Azure's copy and the latest main by commit and by every file's bytes; return the audit."""
    latest = fetch_main(repo)
    branch_commit = git(worktree, "rev-parse", "HEAD").strip()
    main_files = manifest(commit_files(repo, commit))
    branch_files = disk_manifest(worktree)
    record = read_marker(container, commit) or {}  # read again from Azure, not the copy taken while waiting
    azure = blob_problems(container, commit, main_files)
    checks = {"main_unchanged": latest == commit,
              "branch_starts_at_main": branch_commit == commit,
              "branch_files_match_main": branch_files == main_files,
              "ready_record_is_for_main": record.get("commit") == commit,
              "ready_record_files_match_main": record.get("files") == main_files,
              "ready_record_unchanged": record == marker,
              "azure_files_match_main": not azure}
    return {"checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "passed": all(checks.values()),
            "checks": checks, "main_commit": commit, "latest_main": latest, "branch_commit": branch_commit,
            "ready_record_commit": record.get("commit"), "files": len(main_files),
            "manifest_sha256": hashlib.sha256(json.dumps(main_files, sort_keys=True).encode()).hexdigest(),
            "branch_differences": differing(branch_files, main_files)[:20], "azure_problems": azure[:20]}


def failure_message(check: dict) -> str:
    """The engineer's one-line message for a failed preflight; no commit IDs."""
    name = next(k for k, ok in check["checks"].items() if not ok)
    n = len(check["branch_differences"]) if name == "branch_files_match_main" else len(check["azure_problems"])
    return "Check failed: " + FAILURES[name].format(n=n) + ". Nothing was sent to the agent"


def draft_from_main(repo: Path, worktrees: Path, number: str, ticket: dict, review: dict, make_agent, container,
                    report=print, wait=wait_for_ready, clock=time.monotonic, max_attempts: int = MAX_ATTEMPTS) -> Draft:
    """Fetch main, wait for its snapshot, branch, call the pinned agent, re-check main; regenerate if it moved."""
    attempts = []
    for attempt in range(1, max_attempts + 1):
        commit = fetch_main(repo)
        report(f"Fetched the latest GitHub main (attempt {attempt} of {max_attempts}).")
        try:
            marker = wait(repo, container, commit, report=report)
        except SyncSuperseded as error:
            report(f"{str(error)[:1].upper()}{str(error)[1:]}. Drafting from the newer main.")
            attempts.append({"attempt": attempt, "main_commit": commit, "superseded": True, **error.detail})
            continue
        started = clock()
        branch, path = add_branch(repo, worktrees, number, commit)
        try:
            check = preflight(repo, path, container, commit, marker)
            if not check["checks"]["main_unchanged"]:
                report("GitHub main changed while the ticket branch was being prepared. Starting again from the new main.")
                attempts.append({"attempt": attempt, "main_commit": commit, "preflight": check,
                                 "restarted": "main moved before the agent call"})
                remove_branch(repo, branch, path)
                continue
            if not check["passed"]:
                raise PreflightFailed(failure_message(check), check)
            report(f"Check passed: the ticket branch, Azure's copy and GitHub main match ({check['files']} files). "
                   "Sending the ticket to the agent.")
            agent = make_agent(path, commit, marker, container)
            reply = agent(ticket, engineer_review=review)
            call = agent.calls[-1] if getattr(agent, "calls", None) else None
            after = fetch_main(repo)
            changed = relevant_changes(repo, commit, after)
            record = {"attempt": attempt, "main_commit": commit, "snapshot": commit, "agent_version": agent.version,
                      "preflight": check,
                      "marker": {k: marker.get(k) for k in ("ready_at", "deploy_run", "checks", "agent")},
                      "response_id": getattr(call, "response_id", None),
                      "tool_commits": list(getattr(call, "commits", []) or []),
                      "main_after": after, "relevant_changes": changed[:20],
                      "finished_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
            attempts.append(record)
            if clock() - started > RUN_DEADLINE.total_seconds():
                raise RunTooLong(f"the draft took longer than {RUN_DEADLINE}; its snapshot is only promised that "
                                 "long, so the reply was thrown away")
            if changed:
                report(f"GitHub main changed {len(changed)} relevant file(s) while the agent was drafting. "
                       "Drafting again from the new main.")
                remove_branch(repo, branch, path)
                continue
            return Draft(reply, commit, branch, path, {"attempts": attempts, "branch": branch,
                                                       "worktree": str(path), "main_commit": commit,
                                                       "snapshot": commit, "agent_version": agent.version})
        except BaseException:
            if path.exists():
                remove_branch(repo, branch, path)
            raise
    raise MainMoving(f"main changed relevant files during each of {max_attempts} attempts; nothing was kept. "
                     "Draft again when main is quiet")
