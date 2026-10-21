"""fwagent: hand a ticket to the workflow, then approve, fix or reject the draft (ADR 0005).

Example: every ticket waits for the engineer, even one with no findings.
    uv run --python 3.11 python -m workflow.cli submit data/tickets/RITM0010043.yaml
    uv run --python 3.11 python -m workflow.cli accept RITM0010043 --ticket-version 3f9a0c51d2e7 --engineer "Jordan Patel" --reason "Checked" --reply reply.json
    uv run --python 3.11 python -m workflow.cli fix RITM0010043 "Port should be 443" --reply fixed.json
    uv run --python 3.11 python -m workflow.cli approve RITM0010043

A ticket with a problem is never rejected by the workflow. It waits as
awaiting_review, and the engineer edits, accepts or rejects it:
    uv run --python 3.11 python -m workflow.cli edit RITM0010043 fixed-ticket.yaml --engineer "Jordan Patel" --note "CIDR from requester"
    uv run --python 3.11 python -m workflow.cli accept RITM0010043 --ticket-version 3f9a0c51d2e7 --engineer "Jordan Patel" --reason "Planned spoke" --planned planned.yaml --reply reply.json
    uv run --python 3.11 python -m workflow.cli reject RITM0010043 "Duplicate of RITM0010040" --engineer "Jordan Patel"

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
5. Every ticket is assumed approved in ServiceNow before it arrives. An edit may not
   change the ticket's state or approvals, so review can never bypass them.
6. A malformed or incomplete ticket is kept, as awaiting_review, and never reaches
   the agent. Only an engineer's edit can clear an invalid or missing address; the
   workflow never picks a reading, normalises a prefix or fills in an address.
7. Accept records the engineer and reason, and refuses while any finding needs an
   edit. It never widens the ticket: the reply still passes every scope and approval
   check, so only the ticket's own values, at its own sites, are written.
8. Accept is bound to one ticket version: the engineer quotes the version printed on
   the review note, and accept refuses if the ticket has changed since. An edit makes
   a new version and clears any earlier acceptance.
9. The agent runs only after acceptance. submit and edit never call it, even for a
   ticket with no findings. This review covers the ticket's details only (source,
   destination, protocol, ports, URL or hostname); accept on the exact version is
   the only way to the agent, and fix reruns it only on a draft acceptance produced.
   The final review of the draft (approve) is a separate, later step.

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

import yaml

from workflow.intake import NEEDS_PLANNED, finding, intake_findings, ticket_version
from workflow.planned import check_planned, missing_spoke_files
from workflow.scope import BackupsRemainError, PartialWriteError, check_no_backups, plan_writes, write_all
from workflow.tfvars_writer import DraftError
from workflow.tickets import load_ticket

REPO = Path(__file__).resolve().parents[1]
DONE, REFUSED, BACKUPS, REVIEW = 0, 1, 3, 4  # exit codes; REVIEW = waiting for the engineer
OPEN = ("awaiting_review", "awaiting_platform_change")  # statuses the engineer can edit, accept or reject


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


def review_note(record: dict) -> str:
    """The note printed when a ticket waits for the engineer: each finding and the three decisions."""
    lines = [f"Review note · {record['number']} · {record['status']} · ticket version {record['ticket_version'][:12]}"]
    for f in record["findings"]:
        tag = "can be accepted" if f["acceptable"] else "needs an edit"
        lines.append(f"  [{f['code']}, {tag}] {f['where']}: {f['message']}")
        lines += [f"      suggestion, not applied: {s['cidr']} {s.get('vnet', '')} {s['environment']} {s['site']} "
                  f"(from {s['source']})" for s in f.get("suggestions", [])]
    lines += [f"  missing: {m}" for m in record.get("missing", [])]
    if not record["findings"] and not record.get("missing"):
        lines.append("  No findings. The agent has not run: accept this exact version to let it draft.")
    lines.append(f"Engineer: fwagent edit {record['number']} TICKET --engineer NAME --note TEXT, "
                 f"accept {record['number']} --ticket-version {record['ticket_version'][:12]} --engineer NAME "
                 f"--reason TEXT, or reject {record['number']} REASON.")
    return "\n".join(lines)


def draft_note(record: dict) -> str:
    """The short note printed after submit or fix: outcome, rules and files, and what has not run yet."""
    if record["status"] in OPEN:
        return review_note(record)
    reply = record["reply"]
    lines = [f"Draft note · {record['number']} · {record['status']}", f"Outcome: {reply['outcome']}"
             + (f", reason {reply['reason']}" if reply.get("reason") else "")
             + (", action remove" if reply.get("action") == "remove" else "")]
    lines += [f"  {k['key']}  in {k['file']}" for k in record["keys"]]
    if record["files"]:
        lines.append("Review the change as a diff: git diff -- infra/envs")
    lines.append("Not run yet: Tier 1 checks and terraform plan (Step 04 Task 06).")
    return "\n".join(lines)


def _apply_reply(repo: Path, record: dict, reply: dict) -> None:
    """Act on the agent's reply: write a draft, park a stop for the engineer, or note that a rule already allows it."""
    record["reply"] = reply
    if reply["outcome"] == "draft":
        record["keys"], record["files"] = _write_draft(repo, record["ticket"], reply, {})
        record["status"], record["findings"] = "drafted", []
    elif reply["outcome"] == "stop_and_ask":  # awaiting engineer review, never a rejection
        record["status"] = "awaiting_review"
        record["findings"] = [finding(reply.get("reason") or "no_reason_given", "(agent)",
                                      reply.get("explanation") or "the agent stopped and asks the engineer")]
    else:
        record["status"] = reply["outcome"]


def submit(repo: Path, ticket_path: str) -> str:
    """Check the ticket and save it for the engineer's review; the agent never runs here."""
    check_no_backups(repo)
    ticket = load_ticket(ticket_path)
    number = ticket.get("number") if isinstance(ticket, dict) else None
    if not isinstance(number, str) or not number.startswith("RITM"):
        raise Refused(f"{ticket_path}: no ticket number, so it cannot be filed for review")
    if ticket.get("state") != "approved":
        raise Refused(f"{number}: ticket state is {ticket.get('state')!r}; only approved tickets are drafted")
    path = record_path(repo, number)
    if path.exists() and json.loads(path.read_text())["status"] in ("drafted",) + OPEN:
        raise Refused(f"{number}: already {json.loads(path.read_text())['status']}; use fix, edit, accept or reject")
    record = {"number": number, "original_ticket": ticket, "ticket": ticket, "ticket_version": ticket_version(ticket),
              "status": "awaiting_review",
              "reply": None, "keys": [], "files": {}, "findings": intake_findings(repo, ticket),
              "history": [{"at": _now(), "action": "submit", "ticket_version": ticket_version(ticket)}]}
    save_record(repo, record)
    return draft_note(record)


def _open(record: dict) -> None:
    """Refuse unless the ticket is waiting for the engineer."""
    if record["status"] not in OPEN:
        raise Refused(f"{record['number']}: the ticket is {record['status']}, not awaiting review")


def edit(repo: Path, number: str, ticket_path: str, engineer: str, note: str) -> str:
    """Replace the ticket with the engineer's edit, record what changed, and run every check again; the agent waits."""
    check_no_backups(repo)
    record = load_record(repo, number)
    _open(record)
    new = load_ticket(ticket_path)
    if not isinstance(new, dict) or new.get("number") != number:
        raise Refused(f"{ticket_path}: the edited ticket must keep number {number}")
    for field in ("state", "approvals"):
        if new.get(field) != record["ticket"].get(field):
            raise Refused(f"{number}: an edit may not change {field}; ServiceNow approvals are not the engineer's to edit")
    old = record["ticket"]
    changes = {k: {"before": old.get(k), "after": new.get(k)} for k in sorted(set(old) | set(new)) if old.get(k) != new.get(k)}
    findings = intake_findings(repo, new)
    record.update(ticket=new, ticket_version=ticket_version(new), findings=findings, missing=[], status="awaiting_review",
                  reply=None)
    record.pop("review", None)  # an acceptance covers the version it was given for, never an edited one
    record["history"].append({"at": _now(), "action": "edit", "engineer": engineer, "note": note, "changes": changes,
                              "ticket_version": record["ticket_version"]})
    save_record(repo, record)
    return draft_note(record)


def accept(repo: Path, number: str, version: str, engineer: str, reason: str, planned_path: str | None,
           reply_path: str | None) -> str:
    """Record the engineer's acceptance of one ticket version, then let the agent draft within the ticket's own scope."""
    check_no_backups(repo)
    record = load_record(repo, number)
    _open(record)
    if len(version) < 12 or not record["ticket_version"].startswith(version):
        raise Refused(f"{number}: the ticket is version {record['ticket_version'][:12]}, not {version!r}; "
                      "read the current review note before accepting")
    blocking = [f for f in record["findings"] if not f["acceptable"]]
    if blocking:
        raise Refused(f"{number}: cannot be accepted while these need an edit with a valid value:\n  "
                      + "\n  ".join(f"{f['code']} {f['where']}: {f['message']}" for f in blocking))
    planned = yaml.safe_load(Path(planned_path).read_text()) if planned_path else []
    if any(f["code"] in NEEDS_PLANNED for f in record["findings"]) and not planned:
        raise Refused(f"{number}: an unknown or planned address needs --planned FILE confirming its CIDR, "
                      "environment, site, firewall policy, spoke code and rule placement")
    errors = check_planned(repo, record["ticket"], planned)
    if errors:
        raise Refused(f"{number}: the planned-address record does not fit the ticket:\n  " + "\n  ".join(errors))
    missing = missing_spoke_files(repo, record["ticket"], planned)
    reply = None if missing else read_reply(reply_path)
    review = {"decision": "accept", "engineer": engineer, "reason": reason, "ticket_version": record["ticket_version"],
              "accepted": [f["code"] for f in record["findings"]], "planned": planned}
    record["history"].append({"at": _now(), "action": "accept", **review})
    record["review"] = review  # the engineer_review a real agent receives with the ticket
    record["missing"] = missing
    if missing:
        record["status"] = "awaiting_platform_change"
    else:
        _apply_reply(repo, record, reply)
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


def reject(repo: Path, number: str, reason: str, engineer: str | None = None) -> str:
    """Close the request: put every drafted file back to its bytes from before the draft, and record the reason."""
    check_no_backups(repo)
    record = load_record(repo, number)
    if record["status"] not in OPEN:
        _drafted(record)
        _unchanged_since_draft(repo, record)
        write_all({repo / rel: f["before"] for rel, f in record["files"].items()})
    record["status"] = "rejected"
    record["history"].append({"at": _now(), "action": "reject", "reason": reason, "engineer": engineer})
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
    s = sub.add_parser("submit", help="check a ticket and save it for the engineer's review; the agent waits")
    s.add_argument("ticket")
    f = sub.add_parser("fix", help="replace the draft with a fixed reply")
    f.add_argument("number")
    f.add_argument("note")
    f.add_argument("--reply", help="replay stand-in: JSON file with the agent's fixed reply")
    r = sub.add_parser("reject", help="close the request: remove any draft and record why")
    r.add_argument("number")
    r.add_argument("reason")
    r.add_argument("--engineer", help="who decided")
    e = sub.add_parser("edit", help="replace a ticket awaiting review with the engineer's edit and check it again")
    e.add_argument("number")
    e.add_argument("ticket")
    e.add_argument("--engineer", required=True)
    e.add_argument("--note", required=True)
    c = sub.add_parser("accept", help="record the engineer's acceptance and let the agent draft")
    c.add_argument("number")
    c.add_argument("--ticket-version", required=True, help="the version on the review note (at least 12 characters)")
    c.add_argument("--engineer", required=True)
    c.add_argument("--reason", required=True)
    c.add_argument("--planned", help="YAML list confirming each planned address: cidr, environment, site, "
                                     "firewall_policy, spoke, placement")
    c.add_argument("--reply", help="replay stand-in: JSON file with the agent's reply")
    a = sub.add_parser("approve", help="approve the draft for the pull request step")
    a.add_argument("number")
    args = parser.parse_args(argv)
    try:
        if args.command == "submit":
            out = submit(repo, args.ticket)
        elif args.command == "fix":
            out = fix(repo, args.number, args.note, args.reply)
        elif args.command == "reject":
            out = reject(repo, args.number, args.reason, args.engineer)
        elif args.command == "edit":
            out = edit(repo, args.number, args.ticket, args.engineer, args.note)
        elif args.command == "accept":
            out = accept(repo, args.number, args.ticket_version, args.engineer, args.reason, args.planned, args.reply)
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
    return REVIEW if out.startswith("Review note") else DONE


if __name__ == "__main__":
    sys.exit(main())
