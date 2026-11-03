"""Snapshots of main in Blob storage, and the marker that says one is ready for drafting.

Example: after a push of commit 4f2a1c9…, the sync job uploads that commit's data/network and
infra/envs files to snapshots/4f2a1c9…/, checks every file's bytes against Git, checks the agent
version, then writes ready/4f2a1c9….json. A ticket drafted from main 4f2a1c9… waits for that
marker, checks it again, and only then calls the agent with 4f2a1c9… as its snapshot.

Why: GitHub main is the source of truth. The agent's tools read a copy of it in Azure, so a draft
is safe only when that copy holds exactly the main revision the ticket branch starts from.

Ready for drafting is not applied in Azure. A marker says the configuration files of one main
commit are copied and checked, and which agent version matches that commit's instructions. It says
nothing about any firewall: uploading a snapshot never changes a firewall rule.

Safety rule: a snapshot is immutable. A file is uploaded once and never overwritten with other
bytes, a marker is written once, and a missing, incomplete, mismatched or older snapshot stops the
draft. An older snapshot is never used instead. A snapshot is deleted only when another commit
replaced it more than GRACE ago, which is far longer than any run may last (RUN_DEADLINE).
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from workflow.agent import DATA, AgentError

READY = "ready/{commit}.json"
SNAPSHOTS = "snapshots/{commit}/"
MEANING = ("Ready for drafting: this main commit's configuration files are in Blob storage, checked byte for byte "
           "against Git, and the agent version matches this commit's instructions. Not a record of anything applied "
           "to an Azure firewall.")
RUN_DEADLINE = timedelta(minutes=30)  # a draft attempt that runs longer writes nothing
GRACE = timedelta(hours=24)  # a replaced snapshot is kept this long, so no run can outlive its snapshot
WAIT_TIMEOUT = 600  # seconds a draft waits for the sync job before it stops
WAIT_INTERVAL = 15  # seconds between checks while it waits


class SnapshotError(AgentError):
    """The main revision has no usable snapshot; nothing is drafted. The message is plain; IDs go in detail."""

    def __init__(self, message: str, detail: dict | None = None):
        """Keep the plain message for the engineer and the technical detail for the audit log."""
        super().__init__(message)
        self.detail = detail or {}


class SyncPending(SnapshotError):
    """The sync job has not marked this revision ready within the wait."""


class SyncFailed(SnapshotError):
    """The sync job for this revision failed or was cancelled."""


class SyncSuperseded(SnapshotError):
    """GitHub cancelled this revision's sync because a newer push replaced it; draft from the newer main."""


class SnapshotMismatch(SnapshotError):
    """The snapshot or its marker does not hold exactly this revision's files."""


def git(repo: Path, *args: str, binary: bool = False, stdin: bytes | None = None):
    """Run git in repo and return its output; any failure is a SnapshotError."""
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, input=stdin)
    if done.returncode != 0:
        raise SnapshotError(f"git {' '.join(args)} failed: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout if binary else done.stdout.decode()


def commit_files(repo: Path, commit: str) -> dict[str, bytes]:
    """Every data file the commit holds, with its exact bytes, read from Git."""
    listing = git(repo, "ls-tree", "-r", commit, "--", *DATA)
    entries = [line.split("\t", 1) for line in listing.splitlines() if line]
    paths = [path for _, path in entries]
    oids = [meta.split()[2] for meta, _ in entries]
    out = git(repo, "cat-file", "--batch", binary=True, stdin="".join(f"{o}\n" for o in oids).encode())
    files, at = {}, 0
    for path in paths:
        header_end = out.index(b"\n", at)
        size = int(out[at:header_end].split()[2])
        files[path] = out[header_end + 1:header_end + 1 + size]
        at = header_end + 1 + size + 1
    return files


def manifest(files: dict[str, bytes]) -> dict[str, str]:
    """The SHA-256 of each file's bytes, by path."""
    return {path: hashlib.sha256(data).hexdigest() for path, data in sorted(files.items())}


def disk_manifest(worktree: Path) -> dict[str, str]:
    """The SHA-256 of each data file on disk in a checkout: tracked files plus untracked ones Git does not ignore."""
    listed = git(worktree, "ls-files", "-z", "--cached", "--others", "--exclude-standard", "--", *DATA)
    out = {}
    for path in sorted({p for p in listed.split("\0") if p}):
        file = Path(worktree) / path
        if file.is_file():  # a tracked file deleted on disk is simply missing here
            out[path] = hashlib.sha256(file.read_bytes()).hexdigest()
    return out


def differing(a: dict[str, str], b: dict[str, str]) -> list[str]:
    """Paths whose hash differs between two manifests, or that only one of them has."""
    return sorted(p for p in set(a) | set(b) if a.get(p) != b.get(p))


def blob_problems(container, commit: str, wanted: dict[str, str]) -> list[str]:
    """Every way the uploaded snapshot differs from the wanted manifest: missing, extra or changed files."""
    prefix = SNAPSHOTS.format(commit=commit)
    names = {b.name[len(prefix):] for b in container.list_blobs(name_starts_with=prefix)}
    problems = [f"missing {p}" for p in sorted(set(wanted) - names)]
    problems += [f"extra {p}" for p in sorted(names - set(wanted))]
    for path in sorted(set(wanted) & names):
        data = container.download_blob(prefix + path).readall()
        if hashlib.sha256(data).hexdigest() != wanted[path]:
            problems.append(f"changed {path}")
    return problems


def read_marker(container, commit: str) -> dict | None:
    """The ready marker for commit, or None when the sync job has not written it."""
    names = {b.name for b in container.list_blobs(name_starts_with=READY.format(commit=commit))}
    if READY.format(commit=commit) not in names:
        return None
    try:
        return json.loads(container.download_blob(READY.format(commit=commit)).readall())
    except ValueError as error:
        raise SnapshotMismatch(f"the ready marker for {commit[:12]} is not valid JSON") from error


def verify_ready(repo: Path, container, commit: str) -> dict | None:
    """The marker for commit after checking it and every snapshot file against Git; None while it is not written."""
    marker = read_marker(container, commit)
    if marker is None:
        return None
    if marker.get("commit") != commit:
        raise SnapshotMismatch("Azure's ready record belongs to a different version of GitHub main",
                               {"main_commit": commit, "marker_commit": marker.get("commit")})
    wanted = manifest(commit_files(repo, commit))
    if marker.get("files") != wanted:
        raise SnapshotMismatch("Azure's ready record lists different files from GitHub main",
                               {"main_commit": commit, "differing": differing(marker.get("files") or {}, wanted)[:20]})
    problems = blob_problems(container, commit, wanted)
    if problems:
        raise SnapshotMismatch(f"Azure's copy of GitHub main differs in {len(problems)} file(s)",
                               {"main_commit": commit, "problems": problems[:20]})
    return marker


def github_sync_state(commit: str) -> str | None:
    """The sync job's state for commit from GitHub: running, succeeded, cancelled or failed; None if not visible."""
    try:
        done = subprocess.run(["gh", "run", "list", "--workflow", "sync-network.yml", "--commit", commit,
                               "--json", "status,conclusion", "--limit", "1"], capture_output=True, text=True, timeout=30)
        runs = json.loads(done.stdout) if done.returncode == 0 else []
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return None
    if not runs:
        return None
    if runs[0].get("status") != "completed":
        return "running"
    conclusion = runs[0].get("conclusion")
    return "succeeded" if conclusion == "success" else "cancelled" if conclusion == "cancelled" else "failed"


def wait_for_ready(repo: Path, container, commit: str, report=print, sync_state=github_sync_state,
                   timeout: float = WAIT_TIMEOUT, interval: float = WAIT_INTERVAL, clock=time.monotonic,
                   sleep=time.sleep) -> dict:
    """Wait a bounded time for main's snapshot to be marked ready, reporting progress; stop on failure or timeout."""
    start = clock()
    while True:
        marker = verify_ready(repo, container, commit)
        if marker is not None:
            return marker
        state = sync_state(commit)
        if state == "cancelled":
            raise SyncSuperseded("the copy to Azure was cancelled because a newer change to GitHub main replaced it",
                                 {"main_commit": commit, "sync_job": state})
        if state == "failed":
            raise SyncFailed("copying GitHub main to Azure failed. Re-run sync-network in GitHub Actions; an older "
                             "copy is never used instead", {"main_commit": commit, "sync_job": state})
        waited = clock() - start
        if waited >= timeout:
            raise SyncPending(f"Azure's copy of GitHub main is still not ready after {int(waited)}s. Nothing was "
                              "drafted; try again when sync-network has finished",
                              {"main_commit": commit, "sync_job": state, "waited_seconds": int(waited)})
        report(f"Waiting for Azure's copy of GitHub main: {int(waited)}s of {int(timeout)}s, "
               f"sync job {state or 'not visible yet'}.")
        sleep(interval)


# ------------------------------------------------------------ the sync job's side


def upload_snapshot(container, commit: str, files: dict[str, bytes]) -> int:
    """Upload each file once; an existing file must already hold the same bytes. Returns how many were uploaded."""
    from azure.core.exceptions import ResourceExistsError
    prefix, uploaded = SNAPSHOTS.format(commit=commit), 0
    for path, data in sorted(files.items()):
        try:
            container.upload_blob(prefix + path, data, overwrite=False)
            uploaded += 1
        except ResourceExistsError:
            if container.download_blob(prefix + path).readall() != data:
                raise SnapshotMismatch(f"snapshot {commit[:12]} already holds other bytes for {path}; "
                                       "a snapshot is never overwritten") from None
    return uploaded


def write_marker(container, marker: dict) -> dict:
    """Write the ready marker once; if it exists, it must say the same thing. Returns the marker in storage."""
    from azure.core.exceptions import ResourceExistsError
    name = READY.format(commit=marker["commit"])
    try:
        container.upload_blob(name, (json.dumps(marker, indent=2) + "\n").encode(), overwrite=False)
        return marker
    except ResourceExistsError:
        existing = json.loads(container.download_blob(name).readall())
        if existing.get("files") != marker["files"] or existing.get("agent") != marker["agent"]:
            raise SnapshotMismatch(f"a different ready marker for {marker['commit'][:12]} already exists") from None
        return existing


def prune(container, keep: str, now: datetime | None = None, grace: timedelta = GRACE) -> list[str]:
    """Delete snapshots replaced more than grace ago; never the kept commit, the newest marker, or a recent one."""
    now = now or datetime.now(timezone.utc)
    markers = []
    for blob in container.list_blobs(name_starts_with="ready/"):
        data = json.loads(container.download_blob(blob.name).readall())
        markers.append((datetime.fromisoformat(data["ready_at"]), data["commit"]))
    markers.sort()
    replaced = {commit: markers[i + 1][0] for i, (_, commit) in enumerate(markers[:-1])}
    newest = markers[-1][1] if markers else None
    folders: dict[str, list] = {}
    for blob in container.list_blobs(name_starts_with="snapshots/"):
        folders.setdefault(blob.name.split("/")[1], []).append(blob)
    deleted = []
    for commit, blobs in sorted(folders.items()):
        if commit in (keep, newest):
            continue
        if commit in replaced:
            old = replaced[commit] < now - grace
        elif commit in dict((c, t) for t, c in markers):
            old = False
        else:  # never marked ready: a failed sync's leftovers
            old = all(getattr(b, "last_modified", now) < now - grace for b in blobs)
        if old:
            for blob in blobs:
                container.delete_blob(blob.name)
            deleted.append(commit)
    return deleted
