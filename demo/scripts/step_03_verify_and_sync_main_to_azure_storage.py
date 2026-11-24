"""Verify that Azure Storage holds the latest GitHub main, and sync it there only after the engineer confirms.

Example: uv run python demo/scripts/step_03_verify_and_sync_main_to_azure_storage.py
fetches origin and runs six checks for origin/main. When all pass it prints "Already synced and ready for drafting."
When Azure's copy is behind or incomplete, it shows every difference, asks before syncing, starts the project's
sync-network GitHub workflow, waits for it, then runs all six checks again. Check 6 asks the deployed tool
server for its code hash; a sync cannot fix that one, so a stale server is reported, never synced.

Why: the agent's tools read a copy of main in Azure Storage, and the agent version must match main's instructions.
A ticket is sent only when that copy, its ready record and the agent all belong to the same main commit.

Safety rule: verifying only reads; its one write is `git fetch`. A sync starts only after an explicit "y" or "yes"
for the commit and differences shown, and only through the sync-network workflow, which copies GitHub main
itself, never local files or the demo branch. It will not start a sync that would publish a new agent version,
delete old snapshots you have not approved, or try to repair a snapshot that holds different bytes. Sign-in,
network and other errors are reported as errors, never as a reason to sync. It never submits a ticket, calls
the model, merges or touches a firewall.

Step 4 runs these same checks itself through checked(), which returns the verified commit, snapshot and agent
as values; this file stays runnable on its own as a check you can repeat at any time.
"""

# =====================================================================================
#  SETTINGS. Nothing here needs changing for a normal demo run.
# =====================================================================================
REMOTE = "origin"                  # the GitHub remote
MAIN_BRANCH = "main"               # Azure must hold REMOTE/MAIN_BRANCH
SYNC_WORKFLOW = "sync-network.yml" # the project's sync: GitHub main -> Azure Storage (.github/workflows/)
FIND_RUN_SECONDS = 180             # how long to wait for the started sync run to appear on GitHub
SYNC_SECONDS = 900                 # how long to wait for that run to finish (the job's own limit is 10 minutes)
POLL_SECONDS = 10                  # seconds between progress checks
CLOCK_SKEW_SECONDS = 120           # allowed clock difference between this Mac and GitHub
DEFINITION_SETTINGS = ("FWAGENT_MODEL", "FWAGENT_MCP_CONNECTION")  # if set, the local agent hash differs from main's
# =====================================================================================

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from dataclasses import dataclass, field  # noqa: E402
from datetime import datetime, timedelta, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from workflow import deploy, tool_server  # noqa: E402
from workflow.agent import (AGENT_NAME, AgentError, check_version, connect, definition_sha, evaluated,  # noqa: E402
                            local_definition, snapshot_container)
from workflow.snapshot import SNAPSHOTS, blob_problems, commit_files, manifest, prune, read_marker  # noqa: E402

UPSTREAM = f"{REMOTE}/{MAIN_BRANCH}"
READY, NOT_READY, ERROR, BLOCKED = 0, 1, 2, 3  # exit codes
QUESTION = "Do you want to sync the latest GitHub main to Azure Storage? [y/N] "
SLEEP = time.sleep


class SyncFailed(Exception):
    """The sync workflow could not be started, did not finish, or synced another commit."""


# ------------------------------------------------------------------ Git and GitHub


def git(repo: Path, *args: str) -> str:
    """Run git in repo and return its trimmed output; a failure raises with git's message."""
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def gh(*args: str) -> str:
    """Run the GitHub CLI in the repository and return its output; a failure raises with its message."""
    done = subprocess.run(["gh", *args], cwd=REPO, capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"gh {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def fetch_main(repo: Path) -> str:
    """Fetch the remote and return the latest main commit; the checked-out branch is left as it is."""
    git(repo, "fetch", REMOTE)
    return git(repo, "rev-parse", UPSTREAM)


def sync_runs() -> list[dict]:
    """The latest sync-network runs on GitHub, newest first."""
    fields = "databaseId,headSha,status,conclusion,createdAt,event,url"
    return json.loads(gh("run", "list", "--workflow", SYNC_WORKFLOW, "--limit", "20", "--json", fields) or "[]")


# ------------------------------------------------------------------ the six checks


def git_problems(repo: Path, commit: str) -> list[str]:
    """Every reason this checkout cannot stand for origin/main: uncommitted changes, another HEAD, or definition settings."""
    problems = []
    dirty = git(repo, "status", "--short")
    if dirty:
        problems.append(f"the working tree has uncommitted changes: {len(dirty.splitlines())} entr(ies)")
    head = git(repo, "rev-parse", "HEAD")
    if head != commit:
        problems.append(f"HEAD is {head[:12]}, not {UPSTREAM} {commit[:12]}")
    for name in DEFINITION_SETTINGS:
        if os.environ.get(name):
            problems.append(f"{name} is set in this shell, so the local agent definition would differ from main's")
    return problems


def current_commit(container) -> str | None:
    """The commit Azure's current.json names, or None when current.json does not exist; read errors are raised."""
    if "current.json" not in {b.name for b in container.list_blobs(name_starts_with="current.json")}:
        return None
    current = json.loads(container.download_blob("current.json").readall())
    return current.get("commit") if isinstance(current, dict) else None


def manifest_sha256(files: dict[str, str]) -> str:
    """One hash for a snapshot's whole file list, computed the way the drafting code's pre-call check does."""
    return hashlib.sha256(json.dumps(files, sort_keys=True).encode()).hexdigest()


def snapshot_state(repo: Path, container, commit: str) -> tuple[int, int, list[str], list[str], list[str]]:
    """Git's file count, Azure's file count, and the missing, extra and changed snapshot files for this commit."""
    wanted = manifest(commit_files(repo, commit))
    prefix = SNAPSHOTS.format(commit=commit)
    in_azure = len(list(container.list_blobs(name_starts_with=prefix)))
    problems = blob_problems(container, commit, wanted, contents=True)
    split = {kind: [p.split(" ", 1)[1] for p in problems if p.startswith(kind + " ")]
             for kind in ("missing", "extra", "changed")}
    return len(wanted), in_azure, split["missing"], split["extra"], split["changed"]


def agent_problems(repo: Path, container, project, commit: str) -> tuple[dict | None, list[str]]:
    """The ready marker, and every way it, the evaluated register and Foundry disagree with main's agent definition."""
    marker = read_marker(container, commit)
    if marker is None:
        return None, [f"there is no ready marker for {commit[:12]}"]
    problems = []
    if marker.get("commit") != commit:
        problems.append(f"the ready marker names {str(marker.get('commit'))[:12]}, not {commit[:12]}")
    if marker.get("status") != "ready_for_drafting":
        problems.append(f"the ready marker's status is {marker.get('status')!r}")
    agent = marker.get("agent") or {}
    version, sha = str(agent.get("version")), agent.get("definition_sha")
    if agent.get("name") != AGENT_NAME:
        problems.append(f"the ready marker names agent {agent.get('name')!r}, not {AGENT_NAME}")
    body = local_definition(repo)
    if definition_sha(body) != sha:
        problems.append(f"main's agent definition is {definition_sha(body)}, the ready marker says {sha}")
    entry = evaluated(repo).get(sha)
    if entry is None:
        problems.append(f"definition {sha} is not in agents/evaluated-definitions.json")
    elif str(entry.get("agent_version")) != version:
        problems.append(f"the register says version {entry.get('agent_version')}, the ready marker says {version}")
    try:
        check_version(project, version, body)
    except AgentError as error:
        problems.append(str(error))
    return marker, problems


def foundry_versions(project) -> list:
    """The agent's versions on Foundry, lowest number first."""
    return sorted(project.agents.list_versions(AGENT_NAME), key=lambda v: int(v.version))


@dataclass(frozen=True)
class Verified:
    """What passing all six checks proved for one run: the exact commit, snapshot, ready record, agent and tool code."""

    commit: str
    snapshot: str  # the snapshot folder in Azure Storage, snapshots/<commit>/
    files: int
    manifest_sha256: str
    marker: dict
    agent_name: str
    agent_version: str
    definition_sha: str
    tool_code_sha256: str | None = None

    def record(self) -> dict:
        """The values to save in a status record; the ready record itself is named by its time, not copied."""
        return {"commit": self.commit, "snapshot": self.snapshot, "files": self.files,
                "manifest_sha256": self.manifest_sha256, "ready_at": self.marker.get("ready_at"),
                "agent_name": self.agent_name, "agent_version": self.agent_version,
                "definition_sha": self.definition_sha, "tool_code_sha256": self.tool_code_sha256}


@dataclass
class Verification:
    """What the six checks found for one main commit."""

    commit: str
    current: str | None = None
    git_files: int = 0
    azure_files: int = 0
    missing: list = field(default_factory=list)
    extra: list = field(default_factory=list)
    changed: list = field(default_factory=list)
    marker: dict | None = None
    agent: list = field(default_factory=list)
    deploy_ok: bool = False
    manifest_sha256: str | None = None
    tool_problems: list = field(default_factory=lambda: ["not checked"])
    tool_code: dict | None = None

    def verified(self) -> Verified | None:
        """The proven values when all checks passed, else None."""
        if not self.ready():
            return None
        agent = self.marker.get("agent") or {}
        return Verified(self.commit, SNAPSHOTS.format(commit=self.commit), self.git_files, self.manifest_sha256,
                        self.marker, agent.get("name"), str(agent.get("version")), agent.get("definition_sha"),
                        (self.tool_code or {}).get("code_sha256"))

    def storage_ok(self) -> bool:
        """Whether Azure's snapshot holds exactly main's files and bytes."""
        return not (self.missing or self.extra or self.changed)

    def ready(self) -> bool:
        """Whether all of checks 2 to 6 passed."""
        return (self.current == self.commit and self.storage_ok() and self.marker is not None and not self.agent
                and self.deploy_ok and not self.tool_problems)

    def fingerprint(self) -> tuple:
        """The state the engineer confirmed: commit, pointer, file differences and whether a marker exists."""
        return (self.commit, self.current, tuple(self.missing), tuple(self.extra), tuple(self.changed),
                self.marker is not None)


def report(number: int, title: str, problems: list[str], details: list[str]) -> bool:
    """Print one check's PASS or FAIL with its details and problems; return whether it passed."""
    print(f"{number}. {title}: {'PASS' if not problems else 'FAIL'}")
    for line in details:
        print(f"   {line}")
    for problem in problems:
        print(f"   problem: {problem}")
    return not problems


def verify(repo: Path, commit: str, container, project) -> Verification:
    """Run checks 2 to 6 for commit, print each result, and return what they found."""
    v = Verification(commit)
    v.current = current_commit(container)
    report(2, f"Azure current.json names {UPSTREAM}",
           [] if v.current == commit else [f"current.json names {short(v.current)}, not {commit[:12]}"], [])
    v.git_files, v.azure_files, v.missing, v.extra, v.changed = snapshot_state(repo, container, commit)
    v.manifest_sha256 = manifest_sha256(manifest(commit_files(repo, commit)))
    report(3, f"Snapshot matches {UPSTREAM} (count, paths, bytes)",
           [f"{len(v.missing)} missing, {len(v.extra)} extra, {len(v.changed)} changed"] if not v.storage_ok() else [],
           [f"files in Git: {v.git_files}", f"files in Azure: {v.azure_files}"])
    v.marker, v.agent = agent_problems(repo, container, project, commit)
    agent = (v.marker or {}).get("agent") or {}
    versions = ", ".join(str(x.version) for x in foundry_versions(project)) or "none"
    report(4, "Ready marker, agent version and definition match", v.agent,
           [f"ready marker: {(v.marker or {}).get('status', 'missing')}",
            f"agent: {agent.get('name')} v{agent.get('version')}, definition {agent.get('definition_sha')}",
            f"Foundry versions: {versions}"])
    print("5. Project readiness check (python -m workflow.deploy check):")
    v.deploy_ok = deploy.main(["check", "--commit", commit]) == 0
    v.tool_code, v.tool_problems, details = tool_code_state(repo, commit)
    report(6, f"Deployed tool server runs {UPSTREAM}'s mcp/ code", v.tool_problems, details)
    return v


def tool_code_state(repo: Path, commit: str) -> tuple[dict | None, list[str], list[str]]:
    """Ask the deployed tool server for its code hash; return the match, any problem, and the lines to print."""
    try:
        code = tool_server.check(repo, commit)
    except AgentError as error:
        return None, [str(error)], []
    return code, [], [f"code hash {code['code_sha256'][:12]} over {code['files']} files, same as main's mcp/"]


def short(commit: str | None) -> str:
    """The first 12 characters of a commit, or 'nothing' when there is none."""
    return commit[:12] if commit else "nothing (current.json is missing)"


# ------------------------------------------------------------------ differences and what a sync would do


def show_differences(v: Verification) -> None:
    """Print every difference between GitHub main and Azure that the checks found."""
    print("\nDifferences found:")
    print(f"  GitHub {UPSTREAM}:        {v.commit}")
    print(f"  Azure current snapshot:  {v.current or 'none (current.json is missing)'}")
    if v.azure_files == 0:
        print(f"  Snapshot for {v.commit[:12]}: not in Azure yet (0 files). Nothing was read wrongly; it is absent.")
    for label, paths in (("Files missing from Azure", v.missing), ("Extra files in Azure", v.extra),
                         ("Files with different contents", v.changed)):
        print(f"  {label}: {len(paths)}")
        for path in paths[:20]:
            print(f"    {path}")
        if len(paths) > 20:
            print(f"    ... and {len(paths) - 20} more")
    print(f"  Ready marker: {'present' if v.marker is not None else 'missing'}")
    for problem in (v.agent if v.marker is not None else []):
        print(f"  Marker or agent mismatch: {problem}")
    for problem in v.tool_problems:
        print(f"  Tool server: {problem}")


def unfixable(v: Verification) -> list[str]:
    """Every difference a sync cannot repair, so the engineer must look into it instead."""
    reasons = []
    if v.changed:
        reasons.append(f"Azure's snapshot for {v.commit[:12]} holds different bytes in {len(v.changed)} file(s). "
                       "Snapshots are never overwritten, so a sync cannot repair this. Find out why first.")
    if v.extra:
        reasons.append(f"Azure's snapshot for {v.commit[:12]} has {len(v.extra)} file(s) Git does not have. "
                       "A sync never deletes files from a snapshot, so it cannot repair this.")
    if v.marker is not None and v.agent:
        reasons.append("A ready marker exists but disagrees with main or Foundry. A sync only re-checks an "
                       "existing marker, so it cannot repair this.")
    if v.tool_problems:
        reasons.append("The deployed tool server does not run main's mcp/ code. A sync copies data and checks the "
                       "agent; it never deploys the tool server. Redeploy mcp/ from main yourself, then run this again.")
    if v.marker is not None and v.storage_ok() and not v.agent and not v.deploy_ok:
        reasons.append("The project's readiness check fails although checks 3 and 4 pass. Look at its message.")
    return reasons


class _DryRun:
    """A container that reads normally but only records deletes, to predict what prune would remove."""

    def __init__(self, container):
        """Wrap the real container."""
        self.container, self.deleted = container, []

    def list_blobs(self, **kwargs):
        """List blobs from the real container."""
        return self.container.list_blobs(**kwargs)

    def download_blob(self, name):
        """Read a blob from the real container."""
        return self.container.download_blob(name)

    def delete_blob(self, name):
        """Record a delete instead of doing it."""
        self.deleted.append(name)


def sync_scope(repo: Path, container, project, v: Verification, approve_prune: bool) -> tuple[list[str], list[str]]:
    """What the sync workflow would do for this commit, and every part of it that needs separate approval."""
    steps, blockers = [], []
    if v.marker is None:
        sha = definition_sha(local_definition(repo))
        match = [x for x in foundry_versions(project) if (getattr(x, "metadata", None) or {}).get("definition_sha") == sha]
        steps.append(f"upload GitHub {UPSTREAM}'s {v.git_files} files at {v.commit[:12]} from GitHub's own checkout; "
                     "files already in Azure must hold the same bytes")
        if match:
            steps.append(f"check every byte, reuse agent version {match[-1].version} (its definition {sha} matches main), "
                         "read it back, then write the ready marker")
        else:
            blockers.append(f"No Foundry agent version has main's definition {sha}, so the sync would publish a new "
                            "agent version. That needs its own approval and evaluation; this script will not start it.")
        if sha not in evaluated(repo):
            blockers.append(f"Main's definition {sha} is not in agents/evaluated-definitions.json, so drafting would "
                            "refuse it even after a sync.")
    else:
        steps.append(f"re-check the existing ready marker for {v.commit[:12]}; upload nothing and publish nothing")
    steps.append(f"point current.json at {v.commit[:12]}")
    dry = _DryRun(container)
    removed = prune(dry, v.commit)
    if removed:
        steps.append(f"delete {len(removed)} replaced snapshot(s), replaced more than 24 hours ago: "
                     + ", ".join(c[:12] for c in removed))
        if not approve_prune:
            blockers.append("The sync would also delete the replaced snapshot(s) listed above. Rerun with "
                            "--approve-prune if you agree.")
    active = [r for r in sync_runs() if r.get("status") != "completed"]
    if active:
        blockers.append(f"A sync-network run is already {active[0].get('status')} ({active[0].get('url')}). "
                        "Wait for it to finish, then run this again.")
    return steps, blockers


# ------------------------------------------------------------------ the sync itself


def start_sync(commit: str) -> dict:
    """Start sync-network on main and return its run, once GitHub lists it."""
    started = datetime.now(timezone.utc) - timedelta(seconds=CLOCK_SKEW_SECONDS)
    print(f"Starting {SYNC_WORKFLOW} on {MAIN_BRANCH} for {commit[:12]}...")
    gh("workflow", "run", SYNC_WORKFLOW, "--ref", MAIN_BRANCH)
    deadline = time.monotonic() + FIND_RUN_SECONDS
    while True:
        for run in sync_runs():
            created = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00"))
            if run.get("event") == "workflow_dispatch" and created >= started:
                print(f"Sync run started: {run.get('url')}")
                return run
        if time.monotonic() > deadline:
            raise SyncFailed(f"the started run did not appear on GitHub within {FIND_RUN_SECONDS} seconds")
        SLEEP(POLL_SECONDS)


def wait_for_sync(run: dict, commit: str) -> None:
    """Wait for the sync run to finish; raise unless it succeeded for exactly this commit."""
    deadline = time.monotonic() + SYNC_SECONDS
    while True:
        state = json.loads(gh("run", "view", str(run["databaseId"]), "--json", "status,conclusion,headSha,url"))
        print(f"Sync progress: {state.get('status')}")
        if state.get("status") == "completed":
            break
        if time.monotonic() > deadline:
            raise SyncFailed(f"the sync run did not finish within {SYNC_SECONDS} seconds: {state.get('url')}")
        SLEEP(POLL_SECONDS)
    if state.get("headSha") != commit:
        raise SyncFailed(f"the run synced {str(state.get('headSha'))[:12]}, not the confirmed {commit[:12]}; "
                         "main moved before it started")
    if state.get("conclusion") != "success":
        raise SyncFailed(f"the sync run ended with {state.get('conclusion')!r}: {state.get('url')}")


# ------------------------------------------------------------------ the flow


def endpoint() -> str:
    """The Foundry project endpoint: from this shell if set, else read from the 07-foundry Terraform output."""
    if os.environ.get("FWAGENT_PROJECT_ENDPOINT"):
        return os.environ["FWAGENT_PROJECT_ENDPOINT"]
    done = subprocess.run(["terraform", f"-chdir={REPO / 'infra/07-foundry'}", "output", "-json", "project_endpoints"],
                          capture_output=True, text=True)
    if done.returncode != 0:
        raise RuntimeError(f"terraform output failed: {done.stderr.strip()}")
    return json.loads(done.stdout)["AI Foundry API"]


def interactive() -> bool:
    """Whether someone can answer the question at this terminal."""
    return sys.stdin.isatty()


def discard_typeahead() -> None:
    """Throw away anything typed or pasted before the question, so only an answer typed after it counts."""
    if not sys.stdin.isatty():
        return
    try:
        import termios
        termios.tcflush(sys.stdin.fileno(), termios.TCIFLUSH)
    except (ImportError, OSError, ValueError):
        pass  # no terminal control here; the question still asks


def ask(question: str) -> str:
    """Ask one question at the terminal, after discarding earlier keystrokes; end of input counts as no."""
    discard_typeahead()
    try:
        return input(question)
    except EOFError:
        return ""


def check_checkout(repo: Path) -> tuple[str, list[str]]:
    """Fetch main, run check 1 on this checkout, and return main's commit with any problems."""
    commit = fetch_main(repo)
    branch = git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    problems = git_problems(repo, commit)
    report(1, f"Latest {UPSTREAM} and this checkout", problems,
           [f"{UPSTREAM}: {commit}", f"committed {git(repo, 'log', '-1', '--format=%cI %s', commit)}",
            f"this checkout: branch {branch} (left unchanged)"])
    return commit, problems


@dataclass
class Outcome:
    """The result of verify-and-sync: an exit code, and the proven values when it is READY."""

    code: int
    verified: Verified | None = None


def verify_and_sync(repo: Path, approve_prune: bool = False) -> Outcome:
    """Verify; if Azure differs in a way a sync can fix, ask, sync through GitHub, and verify again."""
    while True:
        print("== Verifying ==")
        commit, problems = check_checkout(repo)
        if problems:
            print("\nStopped: this checkout cannot stand for GitHub main, so the checks would not be reliable.")
            print("Fix the problem(s) above yourself, then run this again. Nothing was changed.")
            return Outcome(BLOCKED)
        container, project = snapshot_container(), connect(endpoint())
        v = verify(repo, commit, container, project)
        if v.ready():
            print("\nAlready synced and ready for drafting.")
            return Outcome(READY, v.verified())
        show_differences(v)
        reasons = unfixable(v)
        if reasons:
            print("\nNot syncing:")
            for reason in reasons:
                print(f"  {reason}")
            print("Azure was not changed. Result: NOT READY.")
            return Outcome(NOT_READY)
        steps, blockers = sync_scope(repo, container, project, v, approve_prune)
        print(f"\nThe sync ({SYNC_WORKFLOW}, GitHub {UPSTREAM} -> Azure Storage) would:")
        for step in steps:
            print(f"  - {step}")
        if blockers:
            print("\nNot syncing, separate approval needed:")
            for blocker in blockers:
                print(f"  {blocker}")
            print("Azure was not changed. Result: NOT READY.")
            return Outcome(NOT_READY)
        if not interactive():
            print("\nNot asked: this is not an interactive terminal. Azure was not changed. Result: NOT READY.")
            return Outcome(NOT_READY)
        print(f"\nConfirm for {commit} and the differences shown above.")
        if ask(QUESTION).strip().lower() not in ("y", "yes"):
            print("Not synced. Azure was not changed. Result: NOT READY.")
            return Outcome(NOT_READY)
        latest = fetch_main(repo)
        if latest != commit:
            print(f"\n{UPSTREAM} moved from {commit[:12]} to {latest[:12]} after you answered. "
                  "Showing the new target; confirm again.\n")
            continue
        again = Verification(commit)
        again.current = current_commit(container)
        _, _, again.missing, again.extra, again.changed = snapshot_state(repo, container, commit)
        again.marker = read_marker(container, commit)
        if again.fingerprint() != v.fingerprint():
            print("\nAzure changed after you answered (another sync may have run). Showing the new state; "
                  "confirm again.\n")
            continue
        break

    print("\n== Syncing ==")
    try:
        wait_for_sync(start_sync(commit), commit)
    except Exception as error:
        print(f"SYNC FAILED: {type(error).__name__}: {error}")
        print("The sync may have changed Azure in part. Check the run on GitHub, then run this again. "
              "Result: NOT READY.")
        return Outcome(NOT_READY)
    print("Sync finished.")

    print(f"\n== Verifying again for {commit[:12]} ==")
    try:
        latest = fetch_main(repo)
        v = verify(repo, commit, snapshot_container(), project)
    except Exception as error:
        print(f"\nERROR: the checks after the sync could not run: {type(error).__name__}: {error}")
        print("The sync finished, but its result is not verified. Run this again. Result: NOT READY.")
        return Outcome(ERROR)
    if v.ready() and latest == commit:
        print(f"\nSynced and ready for drafting: Azure holds {UPSTREAM} {commit[:12]}, all six checks pass.")
        return Outcome(READY, v.verified())
    if latest != commit:
        print(f"\n{UPSTREAM} has moved on to {latest[:12]}, so {commit[:12]} is no longer the latest main.")
    if not v.ready():
        show_differences(v)
    print("Result: NOT READY.")
    return Outcome(NOT_READY)


def checked(repo: Path, approve_prune: bool = False) -> Outcome:
    """Verify-and-sync, turning any sign-in, network or tool error into a plain ERROR result, never a sync."""
    try:
        return verify_and_sync(repo, approve_prune)
    except Exception as error:
        print(f"\nERROR: a check could not run: {type(error).__name__}: {error}")
        print("This is an error, not a difference, so it is not a reason to sync. Check az login, gh auth status "
              "and the network, then run this again. Result: NOT READY.")
        return Outcome(ERROR)


def main(argv: list[str] | None = None) -> int:
    """Run the verify-then-sync step on its own and return its exit code."""
    parser = argparse.ArgumentParser(description="Verify GitHub main is in Azure Storage; sync it after you confirm.")
    parser.add_argument("--approve-prune", action="store_true",
                        help="allow the sync to delete snapshots replaced more than 24 hours ago")
    args = parser.parse_args(argv)
    return checked(REPO, args.approve_prune).code


if __name__ == "__main__":
    raise SystemExit(main())
