"""fwagent: hand a ticket to the workflow, then approve, fix or reject the draft (ADR 0005).

Example:
    uv run --python 3.11 python -m workflow.cli submit data/tickets/RITM0010043.yaml --reply reply.json
    uv run --python 3.11 python -m workflow.cli fix RITM0010043 "Port should be 443" --reply fixed.json
    uv run --python 3.11 python -m workflow.cli reject RITM0010043 "Requester withdrew it"
    uv run --python 3.11 python -m workflow.cli approve RITM0010043

Why: the engineer reviews the agent's draft as a normal diff in the tfvars files,
the same change the pull request reviewers will see. Each command is a function,
so pytest drives it like the rest of the workflow.

The agent: no model is configured yet (Step 04 Task 03). Until then the agent is a
replay stand-in: `--reply` names a JSON file holding the reply a model would give.
Without it the command stops and says the model is not configured.

Safety rules:
1. No command starts while a recovery backup from a failed write remains.
2. Only the sites the ticket selects are written (workflow/scope.py).
3. reject, fix and approve first check that every drafted file still has the bytes
   the draft wrote. If a file changed since, the command stops; it never
   overwrites an edit it did not make.
4. The draft record (reply, keys, file bytes before and after) is kept outside the
   repo, under the user's state folder, so it can never be committed.

Not built here: Prompt Shields (Step 04 Task 07), Tier 1 and terraform plan on the
draft note (Step 04 Task 06), the ticket adapter that writes work notes and closes
the ticket, and the pull request (stage 4).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from workflow.scope import BackupsRemainError, PartialWriteError, check_no_backups, plan_writes, write_all
from workflow.tfvars_writer import DraftError
from workflow.tickets import load_ticket, ticket_errors

REPO = Path(__file__).resolve().parents[1]
DONE, REFUSED, BACKUPS = 0, 1, 3  # exit codes


class Refused(Exception):
    """The command cannot go on; the message says why and what to do."""


def state_dir(repo: Path) -> Path:
    """Where draft records live: $FWAGENT_STATE_DIR, else ~/.local/state/fwagent/<repo hash>."""
    if os.environ.get("FWAGENT_STATE_DIR"):
        return Path(os.environ["FWAGENT_STATE_DIR"])
    tag = hashlib.sha256(str(Path(repo).resolve()).encode()).hexdigest()[:12]
    return Path.home() / ".local" / "state" / "fwagent" / tag


def _sha(data: bytes) -> str:
    """The SHA-256 of some bytes, as hex."""
    return hashlib.sha256(data).hexdigest()


def _now() -> str:
    """The current time in UTC, ISO 8601."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def record_path(repo: Path, number: str) -> Path:
    """The draft record file for one ticket."""
    return state_dir(repo) / f"{number}.json"


def load_record(repo: Path, number: str) -> dict:
    """Read a ticket's draft record, or refuse if there is none."""
    path = record_path(repo, number)
    if not path.exists():
        raise Refused(f"{number}: no draft on record; run submit first")
    return json.loads(path.read_text())


def save_record(repo: Path, record: dict) -> None:
    """Write a ticket's draft record, creating the state folder if needed."""
    path = record_path(repo, record["number"])
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(record, indent=2) + "\n")
    os.replace(tmp, path)


def read_reply(path: str | None) -> dict:
    """The replay stand-in: read the agent's reply from a JSON file, or refuse when none is given."""
    if path is None:
        raise Refused("no agent model is configured yet (Step 04 Task 03); pass --reply FILE with the agent's JSON")
    reply = json.loads(Path(path).read_text())
    if not isinstance(reply, dict) or "outcome" not in reply:
        raise Refused(f"{path}: an agent reply is a JSON object with an 'outcome'")
    return reply


def _drafted(record: dict) -> None:
    """Refuse unless the record is a live draft."""
    if record["status"] != "drafted":
        raise Refused(f"{record['number']}: the draft is {record['status']}; nothing to change")


def _unchanged_since_draft(repo: Path, record: dict) -> None:
    """Refuse if any drafted file's bytes differ from what the draft wrote."""
    moved = [rel for rel, f in record["files"].items() if _sha((repo / rel).read_bytes()) != f["after_sha256"]]
    if moved:
        raise Refused(f"{record['number']}: changed since the draft was written, so nothing was touched: "
                      + ", ".join(moved) + ". Undo that edit, or reject and submit again.")


def _write_draft(repo: Path, ticket: dict, reply: dict, base: dict[Path, str]) -> tuple[list, dict]:
    """Write a reply on top of `base` texts; return (written keys, per-file before/after record)."""
    writes = plan_writes(repo, ticket, reply, base)
    final = {path: text for path, text, _ in writes}
    for path, text in base.items():
        final.setdefault(path, text)  # an old draft's file the new one no longer touches goes back to before
    before = {path: (base[path] if path in base else path.read_text()) for path in final}
    write_all(final)
    files = {str(p.relative_to(repo)): {"before": before[p], "before_sha256": _sha(before[p].encode()),
                                        "after_sha256": _sha(final[p].encode())} for p in final}
    keys = [{"file": str(p.relative_to(repo)), "key": k} for p, _, k in writes]
    return keys, files


def draft_note(record: dict) -> str:
    """The short note printed after submit or fix: outcome, rules and files, and what has not run yet."""
    reply = record["reply"]
    lines = [f"Draft note · {record['number']} · {record['status']}", f"Outcome: {reply['outcome']}"
             + (f", reason {reply['reason']}" if reply.get("reason") else "")
             + (", action remove" if reply.get("action") == "remove" else "")]
    lines += [f"  {k['key']}  in {k['file']}" for k in record["keys"]]
    if record["files"]:
        lines.append("Review the change as a diff: git diff -- infra/envs")
    lines.append("Not run yet: Tier 1 checks and terraform plan (Step 04 Task 06).")
    return "\n".join(lines)


def submit(repo: Path, ticket_path: str, reply_path: str | None) -> str:
    """Check the ticket, get the agent's reply, write it into the selected sites and save the draft record."""
    check_no_backups(repo)
    ticket = load_ticket(ticket_path)
    errors = ticket_errors(ticket)
    if errors:
        raise Refused(f"{ticket_path}: ticket fails its checks:\n  " + "\n  ".join(errors))
    if ticket["state"] != "approved":
        raise Refused(f"{ticket['number']}: ticket state is {ticket['state']!r}; only approved tickets are drafted")
    path = record_path(repo, ticket["number"])
    if path.exists() and json.loads(path.read_text())["status"] == "drafted":
        raise Refused(f"{ticket['number']}: already drafted; use fix or reject")
    reply = read_reply(reply_path)
    keys, files = _write_draft(repo, ticket, reply, {}) if reply["outcome"] == "draft" else ([], {})
    record = {"number": ticket["number"], "ticket": ticket, "status": "drafted" if files else reply["outcome"],
              "reply": reply, "keys": keys, "files": files,
              "history": [{"at": _now(), "action": "submit", "agent": "replay", "reply_file": reply_path}]}
    save_record(repo, record)
    return draft_note(record)


def fix(repo: Path, number: str, note: str, reply_path: str | None) -> str:
    """Replace the draft with the agent's fixed reply, in one write, after checking nothing changed since."""
    check_no_backups(repo)
    record = load_record(repo, number)
    _drafted(record)
    _unchanged_since_draft(repo, record)
    reply = read_reply(reply_path)
    if reply["outcome"] != "draft":
        raise Refused(f"{number}: a fix must return a draft; the reply says {reply['outcome']!r}. Reject instead.")
    base = {repo / rel: f["before"] for rel, f in record["files"].items()}
    keys, files = _write_draft(repo, record["ticket"], reply, base)
    record.update(reply=reply, keys=keys, files=files)
    record["history"].append({"at": _now(), "action": "fix", "note": note, "agent": "replay", "reply_file": reply_path})
    save_record(repo, record)
    return draft_note(record)


def reject(repo: Path, number: str, reason: str) -> str:
    """Put every drafted file back to its bytes from before the draft, and record the reason."""
    check_no_backups(repo)
    record = load_record(repo, number)
    _drafted(record)
    _unchanged_since_draft(repo, record)
    write_all({repo / rel: f["before"] for rel, f in record["files"].items()})
    record["status"] = "rejected"
    record["history"].append({"at": _now(), "action": "reject", "reason": reason})
    save_record(repo, record)
    return (f"{number}: draft removed from {len(record['files'])} file(s); reason recorded.\n"
            "Not done yet: closing the ticket as Closed Incomplete and the archive record (ticket adapter not built).")


def approve(repo: Path, number: str) -> str:
    """Mark the draft approved after checking the files still hold exactly what it wrote."""
    check_no_backups(repo)
    record = load_record(repo, number)
    _drafted(record)
    _unchanged_since_draft(repo, record)
    record["status"] = "approved"
    record["history"].append({"at": _now(), "action": "approve"})
    save_record(repo, record)
    return (f"{number}: approved; {len(record['keys'])} rule change(s) in {len(record['files'])} file(s).\n"
            "Not done yet: the pull request on agent/" + number + " (stage 4).")


def main(argv: list[str] | None = None, repo: Path = REPO) -> int:
    """Parse the command line, run one command, print its result and return the exit code."""
    parser = argparse.ArgumentParser(prog="fwagent", description="Draft, fix, reject or approve a firewall change.")
    sub = parser.add_subparsers(dest="command", required=True)
    s = sub.add_parser("submit", help="draft a ticket")
    s.add_argument("ticket")
    s.add_argument("--reply", help="replay stand-in: JSON file with the agent's reply")
    f = sub.add_parser("fix", help="replace the draft with a fixed reply")
    f.add_argument("number")
    f.add_argument("note")
    f.add_argument("--reply", help="replay stand-in: JSON file with the agent's fixed reply")
    r = sub.add_parser("reject", help="remove the draft and record why")
    r.add_argument("number")
    r.add_argument("reason")
    a = sub.add_parser("approve", help="approve the draft for the pull request step")
    a.add_argument("number")
    args = parser.parse_args(argv)
    try:
        if args.command == "submit":
            out = submit(repo, args.ticket, args.reply)
        elif args.command == "fix":
            out = fix(repo, args.number, args.note, args.reply)
        elif args.command == "reject":
            out = reject(repo, args.number, args.reason)
        else:
            out = approve(repo, args.number)
    except (BackupsRemainError, PartialWriteError) as error:
        print(f"refused: {error}")
        return BACKUPS
    except (Refused, DraftError) as error:
        print(f"refused: {error}")
        return REFUSED
    except OSError as error:  # write_all put every file back before raising this
        print(f"failed: {error}; no file was changed")
        return REFUSED
    print(out)
    return DONE


if __name__ == "__main__":
    sys.exit(main())
