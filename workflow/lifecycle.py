"""One unfinished ticket per engineer: the active-ticket register, and how a ticket is finished or abandoned.

Example: rbpal accepts RITM0013002 and the agent drafts it on branch agent/RITM0013002-3899dc4.
Accepting RITM0013003 then stops: it names RITM0013002, its branch and its pull request, and
offers to resume it, finish it once merged, or abandon it. Another engineer is not blocked.

Why: one engineer working several tickets at once leaves half-done drafts that nobody owns.
A ticket is resolved only when its pull request is merged into main (finish) or the engineer
explicitly abandons it (abandon). A failed run alone resolves nothing.

Who the engineer is: the GitHub account the gh command line is signed in to (gh api user).
GitHub authenticated that sign-in, and the same account opens and merges the pull request.
If it cannot be read, the command stops rather than guess.

Safety rule: nothing is decided from local files alone. finish and abandon read the pull
request on GitHub first, and stop when its status cannot be read. finish also checks that
the network snapshot in Azure, which the agent's tools read, already holds the merge.
Artifacts are copied, checked by hash, and only then removed from where they were; an
existing file is never overwritten, and an interrupted move resumes from its manifest. A
branch or worktree holding the engineer's work is deleted only after the engineer types its
name to confirm; finish keeps and reports such a branch and still archives the ticket.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

MANIFEST = "MANIFEST.json"
RESOLUTION = "resolution.json"
NAME = re.compile(r"^RITM\d{7}-[a-z0-9]+$")
MAX_FOLDER = 19  # a ticket folder name is fewer than 20 characters, separators included


class Unverified(Exception):
    """A status or identity this decision needs could not be read; nothing was changed."""


class Blocked(Exception):
    """The action is not allowed in the ticket's current state; the message says what to do."""


def now() -> str:
    """The current time in UTC, ISO 8601."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def run_gh(*args: str) -> str:
    """Run the gh command line and return its output; any failure is Unverified."""
    try:
        done = subprocess.run(["gh", *args], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise Unverified(f"GitHub could not be reached through gh: {error}") from error
    if done.returncode != 0:
        raise Unverified(f"gh {args[0]} failed: {done.stderr.strip() or done.stdout.strip()}")
    return done.stdout


def whoami(gh=None) -> str:
    """The engineer: the GitHub account gh is signed in to."""
    gh = gh or run_gh
    try:
        login = gh("api", "user", "--jq", ".login").strip()
    except Unverified as error:
        raise Unverified(f"cannot tell who you are: {error}. Run gh auth login, then try again") from error
    if not login:
        raise Unverified("cannot tell who you are: gh returned no account. Run gh auth login, then try again")
    return login


def git(repo: Path, *args: str) -> str:
    """Run git in repo and return its output; any failure is Unverified."""
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise Unverified(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout


def repo_id(repo: Path) -> str:
    """The repository: owner/name of its GitHub origin, else the origin URL, else the folder path."""
    try:
        url = git(repo, "remote", "get-url", "origin").strip()
    except Unverified:
        return str(Path(repo).resolve())
    found = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    return found.group(1) if found else url


# ------------------------------------------------------------ the register of active tickets


def register_dir(state: Path) -> Path:
    """Where the active-ticket entries live: one small JSON file per unresolved ticket."""
    return Path(state) / "active"


def entries(state: Path) -> list[dict]:
    """Every active ticket in this state folder, any engineer, oldest first."""
    folder = register_dir(state)
    found = [json.loads(p.read_text()) for p in sorted(folder.glob("RITM*.json"))] if folder.exists() else []
    return sorted(found, key=lambda e: e.get("started_at", ""))


def entry(state: Path, number: str) -> dict | None:
    """The active entry for one ticket, or None."""
    path = register_dir(state) / f"{number}.json"
    return json.loads(path.read_text()) if path.exists() else None


def register(state: Path, number: str, owner: str, repo: str, **fields) -> dict:
    """Add or update a ticket's active entry, written in one step."""
    current = entry(state, number) or {"number": number, "owner": owner, "repo": repo, "started_at": now()}
    current.update({k: v for k, v in fields.items() if v is not None})
    path = register_dir(state) / f"{number}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(current, indent=2) + "\n")
    os.replace(tmp, path)
    return current


def unregister(state: Path, number: str) -> None:
    """Remove a ticket's active entry, once it is merged and archived or abandoned and moved."""
    path = register_dir(state) / f"{number}.json"
    if path.exists():
        path.unlink()


def pr_for(repo: str, branch: str | None, gh=None) -> dict | None:
    """The pull request whose head is branch, from GitHub; None when there is none; Unverified when unreadable."""
    gh = gh or run_gh
    if not branch:
        return None
    out = gh("pr", "list", "--repo", repo, "--head", branch, "--state", "all", "--json",
             "number,url,state,baseRefName,headRefName,mergeCommit,mergedAt,title,body")
    try:
        prs = json.loads(out or "[]")
    except ValueError as error:
        raise Unverified(f"GitHub's answer about branch {branch} could not be read") from error
    if len(prs) > 1:
        raise Unverified(f"{len(prs)} pull requests use branch {branch}; resolve it by hand on GitHub")
    return prs[0] if prs else None


def check_no_unfinished(state: Path, owner: str, repo: str, number: str, gh=None) -> None:
    """Stop when this engineer has another unresolved ticket in this repository; name it and the ways out."""
    gh = gh or run_gh
    open_ = [e for e in entries(state) if e["owner"] == owner and e["repo"] == repo and e["number"] != number]
    if not open_:
        return
    e = open_[0]
    try:
        pr = pr_for(repo, e.get("branch"), gh)
        link = pr["url"] + f" ({pr['state'].lower()})" if pr else "none opened yet"
        merged = bool(pr and pr["state"] == "MERGED")
    except Unverified as error:
        link, merged = f"could not be checked ({error})", False
    lines = [f"{owner} already has an unfinished ticket in {repo}. Finish it or abandon it before starting {number}.",
             f"  Ticket: {e['number']}",
             f"  Branch: {e.get('branch') or 'not drafted yet'}",
             f"  Pull request: {link}",
             "Choose one:",
             f"  Resume it:   fwagent draft {e['number']}   (or review its branch and open the pull request)"]
    lines.append(f"  Finish it:   fwagent finish {e['number']}   (only after its pull request is merged into main)"
                 + ("   <- its pull request is merged" if merged else ""))
    lines.append(f"  Abandon it:  fwagent abandon {e['number']} --reason \"why\"")
    raise Blocked("\n".join(lines))


# ------------------------------------------------------------ folders and the safe move


def default_label(record: dict | None, ticket: dict | None) -> str:
    """A short description for the folder name: spoke and port when a rule was drafted, else protocol and port."""
    ticket = ticket or (record or {}).get("ticket") or {}
    port = str((ticket.get("ports") or [""])[0]).split("-")[0]
    keys = [k.get("key", "") for k in (record or {}).get("keys", [])]
    parts = keys[0].split("-") if keys else []
    head = parts[2] if len(parts) > 2 else str(ticket.get("protocol") or "tkt")
    return re.sub(r"[^a-z0-9]", "", f"{head}{port}".lower())


def folder_name(number: str, label: str) -> str:
    """The ticket folder name: the full ticket number and a short description, fewer than 20 characters."""
    label = re.sub(r"[^a-z0-9]", "", label.lower())[:MAX_FOLDER - len(number) - 1]
    name = f"{number}-{label}"
    if not NAME.fullmatch(name) or len(name) > MAX_FOLDER:
        raise Blocked(f"{name!r} is not a valid ticket folder name: RITM and 7 digits, a dash, then letters or digits, "
                      f"{MAX_FOLDER} characters at most")
    return name


def artifacts(number: str, sources: dict[str, Path]) -> list[tuple[str, Path]]:
    """Every file named for the ticket in each source folder, as (subfolder label, path); folders are left alone."""
    found = []
    for label, folder in sources.items():
        if Path(folder).is_dir():
            found += [(label, p) for p in sorted(Path(folder).iterdir()) if p.is_file() and number in p.name]
    return found


def _sha(path: Path) -> str:
    """The SHA-256 of a file."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def existing_folder(root: Path, number: str) -> Path | None:
    """The ticket's folder under root, if one was already made (a finished or interrupted move)."""
    hits = [p for p in Path(root).glob(f"{number}-*") if p.is_dir()] if Path(root).exists() else []
    return hits[0] if hits else None


def move_artifacts(files: list[tuple[str, Path]], dest: Path, extra: dict[str, str]) -> dict:
    """Copy each file into dest/<label>/, check its hash, then remove the original; resumable, never overwrites."""
    staging = dest.parent / ".staging" / dest.name
    manifest_path = dest / MANIFEST
    if dest.exists() and not manifest_path.exists():
        raise Blocked(f"{dest} already exists and was not made by this workflow; nothing was overwritten")
    if not dest.exists():
        staging.mkdir(parents=True, exist_ok=True)
        moved = {}
        for label, src in files:
            target = staging / label / src.name
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists() and _sha(target) != _sha(src):
                raise Blocked(f"{target} already holds other bytes; nothing was overwritten")
            if not target.exists():
                shutil.copy2(src, target)
            if _sha(target) != _sha(src):
                raise Unverified(f"the copy of {src} does not match it; the original was kept")
            moved[f"{label}/{src.name}"] = {"from": str(src), "sha256": _sha(target)}
        for name, text in extra.items():
            target = staging / name
            if target.exists() and target.read_text() != text:
                raise Blocked(f"{target} already holds other text; nothing was overwritten")
            target.write_text(text)
        (staging / MANIFEST).write_text(json.dumps({"files": moved, "originals_removed": False}, indent=2) + "\n")
        dest.parent.mkdir(parents=True, exist_ok=True)
        os.rename(staging, dest)  # one step: the ticket folder appears complete or not at all
    manifest = json.loads(manifest_path.read_text())
    kept = []
    for rel, info in manifest["files"].items():
        src = Path(info["from"])
        if not src.exists():
            continue
        if _sha(src) == info["sha256"]:
            src.unlink()
        else:
            kept.append(str(src))  # changed after it was copied: never deleted
    manifest.update(originals_removed=not kept, originals_kept=kept)
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest


# ------------------------------------------------------------ branch and worktree cleanup


def branch_work(repo: Path, branch: str, worktree: Path | None, base: str | None) -> list[str]:
    """What the branch or worktree holds beyond its starting commit: uncommitted files and commits."""
    work = []
    if worktree and Path(worktree).exists():
        work += [f"uncommitted: {line[3:]}" for line in git(Path(worktree), "status", "--porcelain",
                                                            "--untracked-files=all").splitlines() if line]
    if base:
        try:
            work += [f"commit: {c}" for c in git(repo, "rev-list", f"{base}..{branch}").split()]
        except Unverified:
            pass  # the branch is already gone
    return work


def delete_branch(repo: Path, branch: str, worktree: Path | None) -> None:
    """Delete a ticket's worktree and branch; callers decide first whether that is allowed."""
    if worktree and Path(worktree).exists():
        git(repo, "worktree", "remove", "--force", str(worktree))
    if git(repo, "branch", "--list", branch).strip():
        git(repo, "branch", "-D", branch)


def summary(record: dict | None, ticket: dict | None) -> str:
    """One line on what the ticket asked for."""
    t = ticket or (record or {}).get("ticket") or {}
    src = ", ".join(str(s.get("cidr") or s.get("ip_group") or s) for s in t.get("sources", []))
    dst = ", ".join(str(d.get("cidr") or d.get("fqdn") or d) for d in t.get("destination", []))
    return (f"{t.get('number')}: {', '.join(t.get('environments', []))} {src} to {dst} "
            f"{t.get('protocol', '')} {','.join(map(str, t.get('ports', [])))} ({t.get('external_party') or 'no external party'})").strip()


# ------------------------------------------------------------ the merge in Azure's snapshot


def azure_synced(repo: Path, merge_commit: str, container=None) -> dict:
    """Check the snapshot Azure's tools read now holds merge_commit and matches Git byte for byte."""
    from workflow.agent import AgentError, snapshot_container
    from workflow.snapshot import verify_ready
    try:
        container = container if container is not None else snapshot_container()
        current = json.loads(container.download_blob("current.json").readall()).get("commit") or ""
    except Exception as error:  # any storage or sign-in failure: the sync cannot be confirmed
        raise Unverified(f"Azure's network snapshot could not be read ({type(error).__name__}). "
                         "Check az login, then run finish again. Nothing was archived") from error
    holds = subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", merge_commit, current],
                           capture_output=True).returncode if current else 1
    if holds == 1:
        raise Blocked(f"the merge {merge_commit[:12]} is not in Azure's network snapshot yet (it holds "
                      f"{current[:12] or 'nothing'}). Wait for sync-network to finish, then run finish again")
    if holds != 0:
        raise Unverified(f"Azure's network snapshot names commit {current[:12]}, which this checkout does not have. "
                         "Run git fetch origin, then run finish again. Nothing was archived")
    try:
        marker = verify_ready(repo, container, current)  # file list and every file's bytes against Git
    except AgentError as error:
        raise Unverified(f"Azure's network snapshot for {current[:12]} does not match Git: {error}. "
                         "Nothing was archived") from error
    if marker is None:
        raise Blocked(f"Azure's network snapshot for {current[:12]} is not marked ready yet. Wait for sync-network "
                      "to finish, then run finish again")
    return {"commit": current, "files_checked": len(marker["files"]), "bytes_match_git": True,
            "agent_version": (marker.get("agent") or {}).get("version")}


def _clean_up_branch(repo: Path, branch: str | None, worktree: Path | None) -> str | None:
    """Delete a fully merged, clean ticket branch; return why it was kept instead, or None."""
    if not branch:
        return None
    try:
        work = branch_work(repo, branch, worktree, "origin/main")
        if work:
            return f"it holds work not in main ({len(work)} item(s): {', '.join(work[:3])})"
        delete_branch(repo, branch, worktree)  # fully merged and nothing uncommitted: nothing to lose
    except Unverified as error:
        return f"it could not be deleted ({error})"
    return None


# ------------------------------------------------------------ finish and abandon


def finish(repo: Path, state: Path, number: str, owner: str, archive: Path, sources: dict[str, Path],
           record: dict | None, ticket: dict | None = None, label: str | None = None, gh=None,
           sync_check=None) -> str:
    """Archive a ticket merged into main and present in Azure's network snapshot; record merged, not applied."""
    gh = gh or run_gh
    sync_check = sync_check or azure_synced
    done = existing_folder(archive, number)
    current = entry(state, number)
    if done is not None and current is None:
        return f"{number} is already archived in {done.name}."
    if current is None:
        raise Blocked(f"{number} is not an active ticket here")
    if current["owner"] != owner:
        raise Blocked(f"{number} belongs to {current['owner']}, not {owner}")
    repo_name = current["repo"]
    if done is None:
        branch = current.get("branch")
        pr = pr_for(repo_name, branch, gh)
        if pr is None:
            raise Blocked(f"{number} has no pull request for branch {branch or '(not drafted)'}. Push the branch and "
                          f"open one, or abandon the ticket")
        if pr["state"] != "MERGED" or pr.get("baseRefName") != "main":
            raise Blocked(f"{number}'s pull request {pr['url']} is {pr['state'].lower()} into {pr.get('baseRefName')}, "
                          "not merged into main. Finish it after the merge, or abandon it")
        merge_commit = (pr.get("mergeCommit") or {}).get("oid")
        git(repo, "fetch", "--quiet", "origin", "main")
        if not merge_commit or subprocess.run(["git", "-C", str(repo), "merge-base", "--is-ancestor", merge_commit,
                                               "origin/main"]).returncode != 0:
            raise Unverified(f"GitHub says {pr['url']} is merged, but its merge commit is not on origin/main here. "
                             "Nothing was archived")
        synced = sync_check(repo, merge_commit)  # before anything moves: the merge must be in Azure's snapshot
        resolution = {"outcome": "merged", "number": number, "engineer": owner, "at": now(), "pr_url": pr["url"],
                      "pr_number": pr["number"], "merge_commit": merge_commit, "merged_at": pr.get("mergedAt"),
                      "branch": branch, "summary": summary(record, ticket),
                      "merged_into_main": True, "network_snapshot_in_azure": synced,
                      "applied_in_azure": "not recorded: merged into main is not the same as applied by the release"}
        if record is not None:
            record["status"] = "merged"
            record["history"].append({"at": resolution["at"], "action": "merged", "engineer": owner,
                                      "pr_url": pr["url"], "merge_commit": merge_commit})
            Path(state, f"{number}.json").write_text(json.dumps(record, indent=2) + "\n")
        name = folder_name(number, label or default_label(record, ticket))
        extra = {RESOLUTION: json.dumps(resolution, indent=2) + "\n",
                 "pull-request.md": f"# {pr.get('title', '')}\n\n{pr['url']}\n\n{pr.get('body') or ''}\n"}
        move_artifacts(artifacts(number, sources), Path(archive) / name, extra)
        done = Path(archive) / name
        worktree = Path(current["worktree"]) if current.get("worktree") else None
        kept = _clean_up_branch(repo, branch, worktree)  # after the archive, so a kept branch never blocks it
        resolution.update(branch_kept=kept is not None, branch_kept_reason=kept)
        (done / RESOLUTION).write_text(json.dumps(resolution, indent=2) + "\n")
    else:
        move_artifacts([], done, {})  # finish an interrupted move from its manifest
        branch = current.get("branch")
        kept = _clean_up_branch(repo, branch, Path(current["worktree"]) if current.get("worktree") else None)
    unregister(state, number)
    tail = f" Branch {branch} was kept: {kept}." if kept else ""
    return (f"{number} is merged into main, in Azure's network snapshot, and archived in {done.name}. "
            f"Applying it to the firewalls is a separate release step.{tail}")


def abandon(repo: Path, state: Path, number: str, owner: str, reason: str, abandoned: Path, sources: dict[str, Path],
            record: dict | None, ticket: dict | None = None, label: str | None = None, remove_branch: bool = False,
            confirm=input, gh=None) -> str:
    """Explicitly give up a ticket: close its open pull request, void its draft and approval, and move its files."""
    gh = gh or run_gh
    if not (reason or "").strip():
        raise Blocked("abandoning a ticket needs a reason")
    done = existing_folder(abandoned, number)
    current = entry(state, number)
    if done is not None and current is None:
        return f"{number} is already abandoned in {done.name}."
    if current is None:
        raise Blocked(f"{number} is not an active ticket here")
    if current["owner"] != owner:
        raise Blocked(f"{number} belongs to {current['owner']}, not {owner}")
    if done is not None:
        move_artifacts([], done, {})
        unregister(state, number)
        return f"{number} finished moving to {done.name}."
    branch = current.get("branch")
    worktree = Path(current["worktree"]) if current.get("worktree") else None
    pr = pr_for(current["repo"], branch, gh)
    if pr and pr["state"] == "MERGED":
        raise Blocked(f"{number}'s pull request {pr['url']} is already merged; run fwagent finish {number} instead")
    kept_branch = bool(branch)
    if remove_branch and branch:
        work = branch_work(repo, branch, worktree, current.get("base"))
        if work:
            typed = confirm(f"Branch {branch} holds work ({len(work)} item(s): {', '.join(work[:3])}). "
                            f"Type the branch name to delete it and its worktree, or press Enter to keep it: ")
            if (typed or "").strip() == branch:
                delete_branch(repo, branch, worktree)
                kept_branch = False
        else:
            delete_branch(repo, branch, worktree)
            kept_branch = False
    pr_closed = False
    if pr and pr["state"] == "OPEN":
        gh("pr", "close", str(pr["number"]), "--repo", current["repo"], "--comment", f"Abandoned: {reason}")
        pr_closed = True
    at = now()
    if record is not None:
        record["invalidated"] = {"at": at, "review": record.pop("review", None),
                                 "approved": record.get("status") == "approved",
                                 "draft_keys": record.get("keys", []), "reply": record.get("reply")}
        record.update(status="abandoned", draft_valid=False, reply=None)
        record["history"].append({"at": at, "action": "abandon", "engineer": owner, "reason": reason,
                                  "pr_url": pr["url"] if pr else None})
        Path(state, f"{number}.json").write_text(json.dumps(record, indent=2) + "\n")
    resolution = {"outcome": "abandoned", "number": number, "engineer": owner, "at": at, "reason": reason,
                  "pr_url": pr["url"] if pr else None, "pr_closed": pr_closed, "branch": branch,
                  "branch_kept": kept_branch, "summary": summary(record, ticket),
                  "draft_and_approval": "invalidated: this draft can no longer be approved or applied"}
    extra = {RESOLUTION: json.dumps(resolution, indent=2) + "\n"}
    if pr:
        extra["pull-request.md"] = f"# {pr.get('title', '')}\n\n{pr['url']}\n\n{pr.get('body') or ''}\n"
    name = folder_name(number, label or default_label(record, ticket))
    move_artifacts(artifacts(number, sources), Path(abandoned) / name, extra)
    unregister(state, number)
    tail = f" Branch {branch} was kept." if kept_branch else ""
    return f"{number} is abandoned and moved to {name}." + (" Its pull request was closed." if pr_closed else "") + tail
