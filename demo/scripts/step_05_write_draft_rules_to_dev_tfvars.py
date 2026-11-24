"""Write the rules step 4 received into the dev rule files on your demo branch, after you say yes.

Example: with TICKET_NUMBER = "RITM0013005" below, while on branch demo/RITM0013005,
    uv run python demo/scripts/step_05_write_draft_rules_to_dev_tfvars.py
reads the reply saved in 02-submit/RITM0013005.status.json, checks it again against the ticket, shows the exact
diff for infra/envs/dev-eastus2 and dev-centralus sett.tfvars in this checkout, and asks once. After "y" it writes
both files and records the keys, files and hashes in the status file.

Why: step 4 saved the agent's reply but wrote nothing. The engineer reviews the rules as a normal diff on the demo
branch, the branch the pull request opens from. The workflow's own writer (workflow/scope.py)
does the write, so the scope, address, protocol and port checks are the ones the workflow uses.

Moving an earlier write: the first version of this script wrote into the draft worktree agent/<ticket>-<commit>
instead. If the status file shows that, this script offers to move the same bytes onto the demo branch and put
the worktree files back to the drafted commit.

Rule name (demo only): the agent drafts the name. Leave RULE_NAME empty to keep it, or set it to the name you
choose; it then replaces the drafted name in every rule, and both names are recorded.

Safety rule: it writes only after an explicit "y" or "yes", only in this checkout on demo/<ticket>, and only the
files the ticket's sites select. It stops, writing nothing, if any saved record changed, the reply is not a draft,
the ticket does not approve a rule, this checkout is not clean on demo/<ticket> at the drafted commit, or GitHub
main moved since the draft. It rechecks all of that after the yes. It never commits, pushes, runs Terraform or
applies anything to Azure.
"""

# =====================================================================================
#  CHANGE THESE FOR EACH NEW TICKET.
# =====================================================================================
TICKET_NUMBER = "RITM0013525"
ENGINEER = "your-github-login"  # must be the engineer who accepted the ticket in step 4, and the account gh is signed in to
RULE_NAME = ""  # empty: keep the agent's drafted name. Set, e.g. "https-sett-to-fourthcoffeeFs": use it in every rule
# =====================================================================================
#  FIXED SETTINGS. Do not change these for a normal demo run.
# =====================================================================================
BRANCH_PREFIX = "demo/"  # you must be on BRANCH_PREFIX + TICKET_NUMBER, e.g. demo/RITM0013005
# =====================================================================================

import argparse  # noqa: E402
import difflib  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import step_03_verify_and_sync_main_to_azure_storage as verification  # noqa: E402  (its ask, which drops type-ahead)
from workflow import lifecycle  # noqa: E402
from workflow.cli import state_dir  # noqa: E402
from workflow.intake import ticket_version  # noqa: E402
from workflow.mainline import fetch_main  # noqa: E402
from workflow.scope import PartialWriteError, check_no_backups, plan_writes, write_all  # noqa: E402
from workflow.tfvars_writer import NAME, DraftError  # noqa: E402

DEMO = Path(__file__).resolve().parents[1]
SUBMIT = DEMO / "02-submit"
NUMBER = re.compile(r"RITM\d{7}")
WRITE_QUESTION = "Write these rules into the files shown above? [y/N] "
MOVE_QUESTION = "Move these rules onto this branch and put the worktree files back? [y/N] "
# exit codes
WRITTEN, STOPPED, NOT_CONFIRMED, WRITE_FAILED = 0, 1, 2, 3


class Stopped(Exception):
    """A check failed; nothing was written."""


def now() -> str:
    """The current time in UTC, as text."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    """The SHA-256 of some bytes, as hex."""
    return hashlib.sha256(data).hexdigest()


def git(where: Path, *args: str) -> str:
    """Run git in one folder and return its trimmed output; a failure stops."""
    done = subprocess.run(["git", "-C", str(where), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise Stopped(f"git {' '.join(args)} failed in {where}: {done.stderr.strip()}")
    return done.stdout.strip()


def git_bytes(where: Path, *args: str) -> bytes:
    """Run git in one folder and return its exact output bytes; a failure stops."""
    done = subprocess.run(["git", "-C", str(where), *args], capture_output=True)
    if done.returncode != 0:
        raise Stopped(f"git {' '.join(args)} failed in {where}: {done.stderr.decode(errors='replace').strip()}")
    return done.stdout


def write_json(path: Path, value: dict) -> None:
    """Write one JSON record, replacing the earlier copy in a single step."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temporary.replace(path)


# ------------------------------------------------------------------ 1. the saved records


def load_records(number: str) -> dict:
    """Read step 4's records and check each one; return them with their bytes and whether to write or move."""
    if not NUMBER.fullmatch(number or ""):
        raise Stopped(f"TICKET_NUMBER is {number!r}; it must be RITM followed by 7 digits")
    status_path, ticket_path, request_path = (SUBMIT / f"{number}.status.json", SUBMIT / f"{number}.yaml",
                                              SUBMIT / f"{number}.json")
    for path in (status_path, ticket_path, request_path):
        if not path.is_file():
            raise Stopped(f"{path.relative_to(DEMO)} does not exist; run step 4 for this ticket first")
    if status_path.with_name(status_path.name + ".tmp").exists():
        raise Stopped(f"{status_path.name}.tmp exists: an earlier record write did not finish. Compare it with "
                      f"{status_path.name} before going on")
    status_bytes = status_path.read_bytes()
    try:
        status = json.loads(status_bytes)
    except ValueError as error:
        raise Stopped(f"{status_path.name} is not valid JSON: {error}") from error
    ticket_bytes = ticket_path.read_bytes()
    if status.get("number") != number:
        raise Stopped(f"{status_path.name} is for {status.get('number')!r}, not {number}")
    write_status = status.get("write_status")
    if write_status == "written" and status.get("write_root") == str(REPO):
        raise Stopped(f"{number}'s rules were already written on {status.get('write_branch')} at "
                      f"{status.get('moved_at') or status.get('written_at')}: {', '.join(status.get('files') or [])}. "
                      "Nothing was changed")
    if write_status in ("writing", "moving"):
        raise Stopped(f"an earlier {write_status[:-3]}e for {number} started at "
                      f"{status.get('write_started_at') or status.get('move_started_at')} and did not record its end. "
                      "Check the rule files with git diff, here and in the draft worktree, before doing anything")
    if write_status == "written":
        mode = "move"  # written by the first version of this script, into the draft worktree
    elif write_status == "not_written":
        mode = "write"
    else:
        raise Stopped(f"{status_path.name} records write_status {write_status!r}; only a reply not yet written is "
                      "written here")
    if status.get("foundry_status") != "succeeded":
        raise Stopped(f"{status_path.name} records foundry_status {status.get('foundry_status')!r}, not succeeded")
    if status.get("used_matches_verified") is not True:
        raise Stopped("the status file does not show the call used the verified commit and agent")
    if status.get("engineer") != ENGINEER or (status.get("review") or {}).get("engineer") != ENGINEER:
        raise Stopped(f"{number} was accepted by {status.get('engineer')!r}, but ENGINEER is {ENGINEER!r}")
    reply = status.get("reply") or {}
    if reply.get("outcome") != "draft":
        raise Stopped(f"the saved outcome is {reply.get('outcome')!r}; only a draft has rules to write")
    if not reply.get("rules"):
        raise Stopped("the saved draft has no rules")
    if sha256(ticket_bytes) != status.get("ticket_sha256"):
        raise Stopped(f"{ticket_path.name} is not the ticket step 4 sent: its bytes changed")
    if sha256(request_path.read_bytes()) != status.get("payload_sha256"):
        raise Stopped(f"{request_path.name} is not the request step 4 sent: its bytes changed")
    ticket = yaml.safe_load(ticket_bytes)
    if not isinstance(ticket, dict) or ticket.get("number") != number or ticket.get("state") != "approved":
        raise Stopped(f"{ticket_path.name} is not an approved ticket {number}")
    if ticket_version(ticket) != status.get("ticket_version"):
        raise Stopped("the ticket's version differs from the version that was accepted")
    return {"status_path": status_path, "status_bytes": status_bytes, "status": status, "ticket_path": ticket_path,
            "ticket_bytes": ticket_bytes, "ticket": ticket, "reply": reply, "mode": mode}


# ------------------------------------------------------------------ 2. this checkout, the register and main


def check_checkout(records: dict) -> None:
    """Check the register entry, this checkout on demo/<ticket>, and GitHub main against step 4's record."""
    status, number = records["status"], records["status"]["number"]
    commit = status.get("main_commit")
    if not (status.get("branch") and status.get("worktree") and commit):
        raise Stopped("the status file names no draft branch, worktree or commit")
    try:
        signed_in = lifecycle.whoami()
        entry = lifecycle.entry(state_dir(REPO), number)
    except (lifecycle.Blocked, lifecycle.Unverified) as error:
        raise Stopped(str(error)) from error
    if signed_in != ENGINEER:
        raise Stopped(f"gh is signed in as {signed_in}, but ENGINEER is {ENGINEER}")
    if not entry:
        raise Stopped(f"{number} has no active register entry; it may have been finished or retired")
    expected = {"owner": ENGINEER, "branch": status["branch"], "worktree": status["worktree"], "base": commit}
    differ = [f"{k} {entry.get(k)!r}, not {v!r}" for k, v in expected.items() if entry.get(k) != v]
    if differ:
        raise Stopped(f"the register entry for {number} differs from the status file: {'; '.join(differ)}")
    branch = BRANCH_PREFIX + number
    current = git(REPO, "rev-parse", "--abbrev-ref", "HEAD")
    if current != branch:
        raise Stopped(f"you are on branch {current}, not {branch}; switch to it first")
    if git(REPO, "rev-parse", "HEAD") != commit:
        raise Stopped(f"{branch} is not at the drafted commit {commit[:12]}; the rule numbers were worked out "
                      "for that commit")
    try:
        check_no_backups(REPO)
    except DraftError as error:
        raise Stopped(str(error)) from error
    changes = git(REPO, "status", "--porcelain", "--untracked-files=all")
    if changes:
        raise Stopped(f"this checkout has changes or untracked files, so nothing was written:\n{changes}")
    latest = fetch_main(REPO)
    if latest != commit:
        raise Stopped(f"GitHub main moved from {commit[:12]} to {latest[:12]} after the draft. The agent's duplicate "
                      "checks and these rule numbers were for the old main. Retire this ticket and start again")


def check_worktree_write(records: dict, changes: list[dict]) -> Path:
    """For a move: the draft worktree must hold exactly the planned new bytes in the recorded files, and nothing else."""
    status = records["status"]
    worktree = Path(status["worktree"])
    if not worktree.is_dir():
        raise Stopped(f"the draft worktree {worktree} does not exist")
    if git(worktree, "rev-parse", "--abbrev-ref", "HEAD") != status["branch"]:
        raise Stopped(f"the worktree {worktree} is not on {status['branch']}")
    if git(worktree, "rev-parse", "HEAD") != status["main_commit"]:
        raise Stopped(f"{status['branch']} is no longer at the drafted commit; it has other commits")
    try:
        check_no_backups(worktree)
    except DraftError as error:
        raise Stopped(str(error)) from error
    if sorted(status.get("files") or []) != sorted(c["file"] for c in changes):
        raise Stopped("the files recorded as written differ from the files the writer plans now")
    lines = sorted(line.strip() for line in git(worktree, "status", "--porcelain", "--untracked-files=all").splitlines())
    if lines != sorted(f"M {c['file']}" for c in changes):  # modified in the working tree only, nothing staged or new
        raise Stopped("the draft worktree holds other changes than the recorded write:\n" + "\n".join(lines))
    hashes = status.get("file_hashes") or {}
    for c in changes:
        now_bytes = (worktree / c["file"]).read_bytes()
        recorded = hashes.get(c["file"]) or {}
        if now_bytes != c["after"] or sha256(now_bytes) != recorded.get("after_sha256"):
            raise Stopped(f"{c['file']} in the draft worktree is not exactly what step 5 wrote")
        if sha256(c["before"]) != recorded.get("before_sha256"):
            raise Stopped(f"{c['file']} on this branch is not the file step 5 wrote over in the worktree")
    return worktree


# ------------------------------------------------------------------ 3. the rule name and the plan


def named_reply(reply: dict, chosen: str) -> tuple[dict, dict]:
    """The reply to write, with the engineer's name if one is set; return it and the name record."""
    drafted = sorted({rule.get("name") for rule in reply["rules"]})
    if not chosen:
        return reply, {"drafted": drafted, "written": drafted, "chosen_by": "agent"}
    if not NAME.fullmatch(chosen):
        raise Stopped(f"RULE_NAME {chosen!r} does not match the rule name format (STD-NAME-03), "
                      "for example https-sett-to-fourthcoffeeFs")
    if len(drafted) != 1:
        raise Stopped(f"the agent drafted different names ({', '.join(map(str, drafted))}); RULE_NAME would give "
                      "them all one name, so set it only when the drafted rules share one name")
    rules = [dict(rule, name=chosen) for rule in reply["rules"]]
    return dict(reply, rules=rules), {"drafted": drafted, "written": [chosen], "chosen_by": ENGINEER}


def moved_reply(records: dict, chosen: str) -> tuple[dict, dict]:
    """For a move: the rules exactly as written before, and their name record; a different RULE_NAME stops."""
    status = records["status"]
    rules, names = status.get("written_rules"), status.get("rule_names")
    if not rules or not names:
        raise Stopped("the status file says written but has no written_rules or rule_names")
    if chosen and names.get("written") != [chosen]:
        raise Stopped(f"the rules were already written as {', '.join(names.get('written') or [])}; a move keeps "
                      f"that name. Leave RULE_NAME empty, or retire the ticket to use {chosen}")
    return dict(records["reply"], rules=rules), names


def plan(root: Path, ticket: dict, reply: dict, dns_answers: list[dict] | None = None) -> list[dict]:
    """Every file change, worked out in memory by the workflow's writer, with each file's bytes before and after.

    dns_answers are the DNS tool's answers step 4 saved from the same response as the reply.
    """
    try:
        writes = plan_writes(root, ticket, reply, dns_answers=dns_answers)
    except DraftError as error:
        raise Stopped(f"the workflow's writer refused the draft, so nothing was written: {error}") from error
    final = {path: text for path, text, _ in writes}  # a later rule in the same file holds the latest text
    changes = []
    for path, text in final.items():
        before = path.read_bytes()
        changes.append({"path": path, "file": str(path.relative_to(root)), "before": before,
                        "after": text.encode(), "keys": [key for p, _, key in writes if p == path]})
    return changes


def show_plan(records: dict, changes: list[dict], names: dict, worktree: Path | None) -> None:
    """Print exactly what the question approves: the branch, the name, any move, and each file's diff."""
    status = records["status"]
    print("\n== Ready to move ==" if worktree else "\n== Ready to write ==")
    print(f"  Ticket:     {status['number']}, version {status['ticket_version'][:12]}, accepted by {status['engineer']}")
    print(f"  Branch:     {BRANCH_PREFIX}{status['number']} at {status['main_commit'][:12]} (= GitHub main)")
    print(f"  Checkout:   {REPO}")
    if names["chosen_by"] == "agent":
        print(f"  Rule name:  {', '.join(names['written'])} (drafted by the agent; set RULE_NAME at the top to change it)")
    else:
        print(f"  Rule name:  {names['written'][0]} (set by {names['chosen_by']}; the agent drafted "
              f"{', '.join(names['drafted'])})")
    if worktree:
        print(f"  Moving:     an earlier run wrote these rules at {status.get('written_at')} into the draft worktree")
        print(f"              {worktree}")
        print(f"              They are written here, then those worktree files go back to {status['main_commit'][:12]}.")
    for change in changes:
        print(f"\n  {change['file']}: adds {', '.join(change['keys'])}")
        diff = difflib.unified_diff(change["before"].decode().splitlines(), change["after"].decode().splitlines(),
                                    f"a/{change['file']}", f"b/{change['file']}", n=2, lineterm="")
        for line in diff:
            print(f"    {line}")


def recheck(records: dict, changes: list[dict], worktree: Path | None) -> None:
    """After the yes: stop unless every record, the checkout, main and each file is exactly what was shown."""
    if records["status_path"].read_bytes() != records["status_bytes"]:
        raise Stopped(f"{records['status_path'].name} changed after it was shown to you")
    if records["ticket_path"].read_bytes() != records["ticket_bytes"]:
        raise Stopped(f"{records['ticket_path'].name} changed after it was shown to you")
    check_checkout(records)
    moved = [c["file"] for c in changes if c["path"].read_bytes() != c["before"]]
    if moved:
        raise Stopped(f"changed after it was shown to you: {', '.join(moved)}")
    if worktree:
        check_worktree_write(records, changes)


# ------------------------------------------------------------------ 4. the write


def write(records: dict, changes: list[dict], names: dict, reply: dict, worktree: Path | None) -> dict:
    """Record the write as started, write every file here, check each reads back, put a moved worktree back, record it."""
    number = records["status"]["number"]
    marker = "moving" if worktree else "writing"
    status = records["status"] | {"write_status": marker, f"{marker[:-3]}e_started_at"
                                  if worktree else "write_started_at": now(),
                                  "write_engineer": ENGINEER, "rule_names": names,
                                  "planned_files": {c["file"]: {"before_sha256": sha256(c["before"]),
                                                                "after_sha256": sha256(c["after"])} for c in changes}}
    write_json(records["status_path"], status)  # if the write dies, the next run sees the marker and stops
    write_all({c["path"]: c["after"].decode() for c in changes})
    wrong = [c["file"] for c in changes if c["path"].read_bytes() != c["after"]]
    if wrong:
        raise OSError(f"did not read back as written: {', '.join(wrong)}")
    done = {"write_status": "written", "write_root": str(REPO), "write_branch": BRANCH_PREFIX + number,
            "keys": [k for c in changes for k in c["keys"]], "files": [c["file"] for c in changes],
            "file_hashes": status["planned_files"], "written_rules": reply["rules"]}
    if worktree:
        originals = {}
        for c in changes:
            data = git_bytes(worktree, "show", f"HEAD:{c['file']}")
            if data != c["before"]:
                raise OSError(f"{c['file']} at the drafted commit is not the file the rules were added to")
            originals[worktree / c["file"]] = data.decode()
        write_all(originals)
        left = git(worktree, "status", "--porcelain", "--untracked-files=all")
        if left:
            raise OSError(f"the draft worktree is not clean after putting its files back:\n{left}")
        done |= {"moved_from": str(worktree), "moved_at": now(),
                 "write_reason": "step 5 wrote the draft into the draft worktree, then moved it onto the demo branch"}
    else:
        done |= {"written_at": now(), "write_reason": "step 5 wrote the draft into the demo branch checkout"}
    status = status | done
    del status["planned_files"]
    write_json(records["status_path"], status)
    return status


# ------------------------------------------------------------------ the flow


def main(argv: list[str] | None = None) -> int:
    """Check step 4's records and this checkout, show the diff, ask, then write (or move) the rules once."""
    argparse.ArgumentParser(description="Write a demo ticket's drafted rules into the dev rule files.").parse_args(argv)
    number = TICKET_NUMBER
    print("== Checking the saved draft and this branch ==")
    worktree = None
    try:
        records = load_records(number)
        check_checkout(records)
        if records["mode"] == "move":
            reply, names = moved_reply(records, RULE_NAME.strip())
        else:
            reply, names = named_reply(records["reply"], RULE_NAME.strip())
        changes = plan(REPO, records["ticket"], reply, records["status"].get("dns_answers"))
        if records["mode"] == "move":
            worktree = check_worktree_write(records, changes)
    except Stopped as error:
        print(f"Stopped. Nothing was written: {error}")
        return STOPPED
    print(f"{number}: records, register entry, branch and GitHub main checks passed; "
          "the workflow's scope and approval checks passed.")

    show_plan(records, changes, names, worktree)
    if not verification.interactive():
        print("\nNot asked: this is not an interactive terminal. Nothing was written.")
        return NOT_CONFIRMED
    question = MOVE_QUESTION if worktree else WRITE_QUESTION
    if verification.ask(f"\n{question}").strip().lower() not in ("y", "yes"):
        print("Not written. Nothing was changed.")
        return NOT_CONFIRMED
    try:
        recheck(records, changes, worktree)
    except Stopped as error:
        print(f"Stopped. Nothing was written: {error}")
        return STOPPED

    try:
        status = write(records, changes, names, reply, worktree)
    except PartialWriteError as error:
        print(f"\nWRITE FAILED and could not be fully undone:\n{error}")
        print("The status file keeps its in-progress marker. Restore the files above before running again.")
        return WRITE_FAILED
    except Exception as error:
        print(f"\nWRITE FAILED: {type(error).__name__}: {error}")
        here_changed = any(c["path"].read_bytes() != c["before"] for c in changes)
        there_changed = worktree is not None and any((worktree / c["file"]).read_bytes() != c["after"] for c in changes)
        if here_changed or there_changed:  # some file holds something new: keep the in-progress marker
            print("At least one file no longer has the bytes it had before. The status file keeps its "
                  "in-progress marker.")
            print(f"Compare the files with: git diff -- infra/envs" + (f"  and  git -C {worktree} diff -- infra/envs"
                                                                         if worktree else ""))
            return WRITE_FAILED
        restored = records["status"] | {"write_failed_at": now(), "write_error": f"{type(error).__name__}: {error}"}
        try:
            write_json(records["status_path"], restored)
        except OSError:
            print("The status file could not be updated; it may still show the in-progress marker.")
        print("Every file still has its earlier bytes. Check with: git status")
        return WRITE_FAILED

    print(f"\nWRITTEN: the rules are in the dev rule files on {BRANCH_PREFIX}{number}.")
    for change in changes:
        print(f"  {change['file']}: {', '.join(change['keys'])}")
    print(f"  Rule name: {', '.join(names['written'])} ({'agent' if names['chosen_by'] == 'agent' else 'engineer'})")
    if worktree:
        print(f"  Moved from the draft worktree; its files are back to {records['status']['main_commit'][:12]}.")
    print(f"  Recorded in {records['status_path'].relative_to(DEMO)}: write_status {status['write_status']}, "
          "branch, keys, files and hashes")
    print("Review the change here: git diff -- infra/envs")
    print("Nothing was committed, pushed, planned or applied.")
    return WRITTEN


if __name__ == "__main__":
    raise SystemExit(main())
