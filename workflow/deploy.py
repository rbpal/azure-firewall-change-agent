"""The sync job's steps: copy one main commit to Blob storage, check it, match the agent, mark it ready.

Example: sync-network runs, for each push to main,
    python -m workflow.deploy ready --commit "$GITHUB_SHA" --run-url "$RUN_URL"
    python -m workflow.deploy prune --keep "$GITHUB_SHA"

Why: drafting needs a snapshot that holds exactly main's files and an agent version that matches
main's instructions. This is the only code that publishes an agent version, so an engineer never
does. A commit that only changes docs or tests still gets its own snapshot and marker, so every
main commit can be drafted from.

Safety rule: it never touches a firewall policy; it writes only to the network-snapshot container
and to the agent's versions. It writes the ready marker last, only after every file's bytes match
Git and the agent version reads back as expected. Any failure leaves no marker, so drafting waits
or stops instead of using an older snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from workflow.agent import (AGENT_NAME, AgentError, check_version, connect, definition_sha, ensure_version,
                            local_definition, snapshot_container)
from workflow.snapshot import (MEANING, SnapshotMismatch, blob_problems, commit_files, git, manifest, prune,
                               read_marker, upload_snapshot, verify_ready, write_marker)

REPO = Path(__file__).resolve().parents[1]


def mark_ready(repo: Path, commit: str, container, project, run_url: str | None = None, now=None) -> dict:
    """Upload commit's files, check every byte, publish or reuse the matching agent version, then write the marker."""
    if git(repo, "rev-parse", "HEAD").strip() != commit:
        raise AgentError(f"this checkout is not at {commit[:12]}; the agent definition must come from that commit")
    if read_marker(container, commit) is not None:
        return verify_ready(repo, container, commit)  # already ready: check it again, change nothing
    files = commit_files(repo, commit)
    wanted = manifest(files)
    upload_snapshot(container, commit, files)
    problems = blob_problems(container, commit, wanted)
    if problems:
        raise SnapshotMismatch(f"snapshot {commit[:12]} does not match Git after upload: " + ", ".join(problems[:5]))
    body = local_definition(repo)
    version = ensure_version(project, body)  # reused while the definition is unchanged
    check_version(project, version, body)
    marker = {"commit": commit, "status": "ready_for_drafting", "meaning": MEANING, "files": wanted,
              "agent": {"name": AGENT_NAME, "version": version, "definition_sha": definition_sha(body),
                        "instructions_sha": hashlib.sha256(body["instructions"].encode()).hexdigest()[:16],
                        "model": body["model"]},
              "checks": {"files": len(wanted), "bytes_match_git": True, "agent_version_read_back": True},
              "deploy_run": run_url,
              "ready_at": (now or datetime.now(timezone.utc)).isoformat(timespec="seconds")}
    return write_marker(container, marker)


def main(argv: list[str] | None = None) -> int:
    """Run one sync step from the command line and print what it did."""
    parser = argparse.ArgumentParser(prog="deploy", description="Mark a main commit ready for drafting.")
    sub = parser.add_subparsers(dest="command", required=True)
    r = sub.add_parser("ready", help="upload, check, match the agent and mark one commit ready")
    r.add_argument("--commit", required=True)
    r.add_argument("--run-url")
    c = sub.add_parser("check", help="check a commit is already ready for drafting; change nothing")
    c.add_argument("--commit", required=True)
    p = sub.add_parser("prune", help="delete snapshots replaced more than the grace period ago")
    p.add_argument("--keep", required=True)
    args = parser.parse_args(argv)
    container = snapshot_container()
    try:
        if args.command == "ready":
            endpoint = os.environ.get("FWAGENT_PROJECT_ENDPOINT")
            if not endpoint:
                raise AgentError("FWAGENT_PROJECT_ENDPOINT is not set")
            marker = mark_ready(REPO, args.commit, container, connect(endpoint), args.run_url)
            print(f"ready for drafting: {args.commit[:12]}, {marker['checks']['files']} files checked, "
                  f"agent {marker['agent']['name']} v{marker['agent']['version']}")
        elif args.command == "check":
            if verify_ready(REPO, container, args.commit) is None:
                raise AgentError(f"{args.commit[:12]} has no ready marker")
            print(f"ready for drafting: {args.commit[:12]}")
        else:
            deleted = prune(container, args.keep)
            print(f"deleted {len(deleted)} replaced snapshot(s): {', '.join(c[:12] for c in deleted) or 'none'}")
    except AgentError as error:
        print(f"not ready: {error}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
