"""Check one demo ticket, verify GitHub main is in Azure Storage, then, after you say yes, send the ticket to Foundry once.

Example: with TICKET_NUMBER = "RITM0013005" below, while on branch demo/RITM0013005,
    uv run python demo/scripts/step_04_verify_and_submit_to_foundry.py
checks the ticket, runs step 3's six checks against freshly fetched GitHub main (offering a sync only if Azure
differs), shows the ticket and the verified commit and agent, and asks once. After "y" it records the engineer's
acceptance of that exact ticket version, saves the request, drafts once, saves the reply in
02-submit/RITM0013005.status.json, and only then moves the ticket to 02-submit/RITM0013005.yaml.

Why: the commit and agent version that were verified are the ones sent, with no hand-copied values. Verifying and
sending in one run shrinks the gap between them from hours to seconds, and the checks below still close it.

Safety rule: it sends at most one request, and only after an explicit "y" or "yes" to the send question; a yes to
a sync is not a yes to send. After that yes it checks the ticket bytes and GitHub main again, and right before
the call the drafting code (workflow/mainline.py) and this script check the snapshot, ready record, agent
version and definition against what was verified. Any change stops it with nothing sent; it never adopts newer
values or starts again by itself. It never publishes an agent version, writes rule files, commits, pushes or
applies. A failed or uncertain call keeps the ticket in 01-waiting and is never sent again automatically.
Existing files are never overwritten. Step 3 stays available on its own to verify and sync without sending.
"""

# =====================================================================================
#  CHANGE THESE FOR EACH NEW TICKET.
# =====================================================================================
TICKET_NUMBER = "RITM0013525"
ENGINEER = "your-github-login"  # must be the GitHub account gh is signed in to
REASON = "Reviewed source, destination, protocol, port and site coverage; approved for drafting only"
# =====================================================================================
#  FIXED SETTINGS. Do not change these for a normal demo run.
# =====================================================================================
BRANCH_PREFIX = "demo/"  # you must be on BRANCH_PREFIX + TICKET_NUMBER, e.g. demo/RITM0013004
# =====================================================================================

import argparse  # noqa: E402
import hashlib  # noqa: E402
import json  # noqa: E402
import os  # noqa: E402
import re  # noqa: E402
import subprocess  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402
from pathlib import Path  # noqa: E402

import yaml  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import step_03_verify_and_sync_main_to_azure_storage as verification  # noqa: E402
import workflow.agent as agent_code  # noqa: E402
from workflow import lifecycle  # noqa: E402
from workflow.agent import AgentError, message, snapshot_container  # noqa: E402
from workflow.cli import acceptance, live_agent, state_dir  # noqa: E402
from workflow.intake import intake_findings, ticket_version  # noqa: E402
from workflow.mainline import draft_from_main  # noqa: E402
from workflow.scope import BackupsRemainError, check_no_backups  # noqa: E402

DEMO = Path(__file__).resolve().parents[1]
WAITING = DEMO / "01-waiting"
SUBMIT = DEMO / "02-submit"
NUMBER = re.compile(r"RITM\d{7}")
SEND_QUESTION = "Accept this exact ticket version and send it to Foundry once? [y/N] "
OUTCOMES = {"draft": "DRAFT RECEIVED: the agent proposed rules. They are saved, not written to any rule file.",
            "already_allowed": "ALREADY ALLOWED: the agent says existing rules already allow this. Nothing to draft.",
            "stop_and_ask": "STOP AND ASK: the agent stopped for engineer review. This is not a draft."}
# exit codes
REPLY_SAVED, NOT_SENT, RESPONSE_UNUSABLE, UNCERTAIN = 0, 1, 2, 3


class Stopped(Exception):
    """A check failed before anything was sent; nothing moved."""


def now() -> str:
    """The current time in UTC, as text."""
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def sha256(data: bytes) -> str:
    """The SHA-256 of some bytes, as hex."""
    return hashlib.sha256(data).hexdigest()


def git(*args: str) -> str:
    """Run git in the repository and return its trimmed output; a failure stops."""
    done = subprocess.run(["git", "-C", str(REPO), *args], capture_output=True, text=True)
    if done.returncode != 0:
        raise Stopped(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done.stdout.strip()


def write_new(path: Path, data: bytes) -> None:
    """Write a file that must not exist yet, flush it to disk, and check it reads back the same."""
    with path.open("xb") as out:
        out.write(data)
        out.flush()
        os.fsync(out.fileno())
    if sha256(path.read_bytes()) != sha256(data):
        raise OSError(f"{path} did not read back as written")


def write_json(path: Path, value: dict) -> None:
    """Write one JSON record, replacing this run's earlier copy in a single step."""
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, default=str) + "\n")
    temporary.replace(path)


# ------------------------------------------------------------------ 1. the ticket, before Azure


def check_ticket(number: str) -> tuple[Path, bytes, dict, str, str]:
    """Every ticket and lifecycle check, before Azure; return the ticket file, its bytes, the ticket, engineer and repo."""
    if not NUMBER.fullmatch(number or ""):
        raise Stopped(f"TICKET_NUMBER is {number!r}; it must be RITM followed by 7 digits")
    used = sorted(SUBMIT.glob(f"{number}*"))
    if used:
        raise Stopped(f"{number} already has a submission in 02-submit: {', '.join(p.name for p in used)}. "
                      "Review it; this script never sends a ticket twice")
    earlier = sorted(p.name for root in (DEMO / "04-archive", DEMO / "05-pr-abandoned") if root.is_dir()
                     for p in root.glob(f"{number}-*"))
    if earlier:
        raise Stopped(f"{number} was already archived or retired ({', '.join(earlier)}); "
                      "a restart uses a fresh ticket number")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH_PREFIX + number:
        raise Stopped(f"you are on branch {branch}, not {BRANCH_PREFIX}{number}; run step 2 for this ticket first")
    path = WAITING / f"{number}.yaml"
    if not path.is_file():
        raise Stopped(f"{path.relative_to(DEMO)} does not exist")
    data = path.read_bytes()
    try:
        ticket = yaml.safe_load(data)
    except yaml.YAMLError as error:
        raise Stopped(f"{path.name} is not valid YAML: {error}") from error
    if not isinstance(ticket, dict) or ticket.get("number") != number:
        raise Stopped(f"{path.name} holds ticket {ticket.get('number') if isinstance(ticket, dict) else None!r}")
    if ticket.get("state") != "approved":
        raise Stopped(f"{number} has state {ticket.get('state')!r}; only an approved ticket is sent")
    findings = intake_findings(REPO, ticket)
    if findings:
        raise Stopped(f"{number} has intake findings: " + "; ".join(f"{f['code']} {f['where']}" for f in findings))
    for ref in ("refs/heads", f"refs/remotes/{os.environ.get('FWAGENT_MAIN_REMOTE', 'origin')}"):
        drafts = git("for-each-ref", "--format=%(refname:short)", f"{ref}/agent/{number}-*")
        if drafts:
            raise Stopped(f"{number} already has a draft branch: {drafts.splitlines()[0]}")
    worktrees = sorted((state_dir(REPO) / "worktrees").glob(f"{number}-*"))
    if worktrees:
        raise Stopped(f"{number} already has a draft worktree: {worktrees[0]}")
    try:
        check_no_backups(REPO)
        owner, repo_id = lifecycle.whoami(), lifecycle.repo_id(REPO)
        if owner != ENGINEER:
            raise Stopped(f"gh is signed in as {owner}, but ENGINEER is {ENGINEER}; the acceptance must be theirs")
        active = lifecycle.entry(state_dir(REPO), number)
        if active and active.get("branch"):
            raise Stopped(f"{number} is already active with draft branch {active['branch']}")
        lifecycle.check_no_unfinished(state_dir(REPO), owner, repo_id, number)
    except (BackupsRemainError, lifecycle.Blocked, lifecycle.Unverified) as error:
        raise Stopped(str(error)) from error
    return path, data, ticket, owner, repo_id


# ------------------------------------------------------------------ 3. what you are asked to approve


def addresses(entries) -> str:
    """The addresses in a ticket's source or destination list, each with its site when it names one."""
    out = []
    for entry in entries or []:
        if not isinstance(entry, dict):
            out.append(str(entry))
            continue
        value = "; ".join(f"{k} {v}" for k, v in entry.items() if k not in ("environment", "site"))
        where = "/".join(str(entry[k]) for k in ("environment", "site") if entry.get(k))
        out.append(f"{value} ({where})" if where else value)
    return ", ".join(out) or "none"


def show_summary(number: str, ticket: dict, version: str, verified) -> None:
    """Print exactly what the send question approves: the ticket's scope, its version, and the verified main and agent."""
    sites = "; ".join(f"{env}: {', '.join(map(str, places))}" for env, places in (ticket.get("change_sites") or {}).items())
    print("\n== Ready to send ==")
    print(f"  Ticket:            {number}, version {version}")
    print(f"  Source:            {addresses(ticket.get('sources'))}")
    print(f"  Destination:       {addresses(ticket.get('destination'))}")
    print(f"  Protocol and port: {ticket.get('protocol')} {', '.join(map(str, ticket.get('ports') or []))}")
    print(f"  Sites:             {sites or 'none'}")
    print(f"  GitHub main:       {verified.commit} (verified in this run)")
    print(f"  Snapshot:          {verified.snapshot}, {verified.files} files, manifest {verified.manifest_sha256[:16]}")
    print(f"  Agent:             {verified.agent_name} v{verified.agent_version}, "
          f"definition {verified.definition_sha}")
    print(f"  Engineer:          {ENGINEER}, reason: {REASON}")


def recheck(source: Path, data: bytes, verified) -> None:
    """After the yes: stop unless the ticket bytes and GitHub main are exactly what was shown."""
    if source.read_bytes() != data:
        raise Stopped(f"{source.name} changed after it was shown to you")
    latest = verification.fetch_main(REPO)
    if latest != verified.commit:
        raise Stopped(f"GitHub main moved from {verified.commit[:12]} to {latest[:12]} after it was verified. "
                      "Run step 4 again; it verifies the new main first")


# ------------------------------------------------------------------ 4. the one call


class Holder:
    """Keeps the agent this run made, so its call record survives an error inside the drafting code."""

    def __init__(self, verified):
        """Start with no agent, bound to what this run verified."""
        self.verified, self.agent, self.would_use = verified, None, None

    def make(self, worktree: Path, commit: str, marker: dict, container):
        """Make the pinned agent, but only for exactly the verified commit, ready record, version and definition."""
        agent = marker.get("agent") or {}
        self.would_use = {"commit": commit, "agent_version": str(agent.get("version")),
                          "definition_sha": agent.get("definition_sha")}
        v = self.verified
        wanted = {"commit": v.commit, "agent_version": v.agent_version, "definition_sha": v.definition_sha}
        differ = [k for k in wanted if self.would_use[k] != wanted[k]]
        if differ:
            raise AgentError(f"drafting would use {', '.join(f'{k} {self.would_use[k]}' for k in differ)}, not the "
                             f"verified {', '.join(f'{k} {wanted[k]}' for k in differ)}; nothing was sent")
        if marker != v.marker:
            raise AgentError("Azure's ready record changed after it was verified; nothing was sent")
        self.agent = live_agent(worktree, commit, marker, container)
        return self.agent

    def call(self):
        """The one Foundry call record, or None when no call was started."""
        calls = getattr(self.agent, "calls", None) or []
        return calls[-1] if calls else None


def call_fields(call) -> dict:
    """What the call record says: request ID, tokens, tools, the commits the tools read, and any error."""
    if call is None:
        return {}
    return {"response_id": call.response_id, "input_tokens": call.input_tokens, "output_tokens": call.output_tokens,
            "tools": call.tools, "tool_calls": call.tool_calls, "tool_snapshots": call.commits,
            "dns_answers": getattr(call, "dns_answers", []),  # the DNS tool's answers in this response; step 5 checks against them
            "call_error": call.error, "raw_reply": call.raw_reply}


def failed_status(status: dict, error: BaseException, call) -> tuple[dict, int]:
    """Classify a failure: nothing sent, sent with an unusable response, or sent with no known response."""
    base = status | call_fields(call) | {"error": f"{type(error).__name__}: {error}",
                                         "detail": getattr(error, "detail", None), "finished_at": now()}
    if call is None:
        return base | {"foundry_status": "not_sent", "failure": "stopped before any request reached Foundry"}, NOT_SENT
    if call.response_id:
        return base | {"foundry_status": "response_unusable",
                       "failure": "Foundry answered, but the answer was refused or could not be used"}, RESPONSE_UNUSABLE
    return base | {"foundry_status": "uncertain",
                   "failure": "the request may have reached Foundry, but no response was received"}, UNCERTAIN


def used_values(draft, holder: Holder) -> dict:
    """The commit, snapshot, agent version and definition the call actually used, from the drafting code's record."""
    preflight = (draft.audit["attempts"][-1].get("preflight") or {})
    return {"commit": draft.commit, "snapshot": verification.SNAPSHOTS.format(commit=draft.commit),
            "manifest_sha256": preflight.get("manifest_sha256"), "agent_version": str(draft.audit["agent_version"]),
            "definition_sha": (holder.would_use or {}).get("definition_sha")}


def move_ticket(source: Path, data: bytes) -> tuple[Path, bool]:
    """Copy the sent ticket bytes into 02-submit, then remove the original only if it still holds those bytes."""
    target = SUBMIT / source.name
    write_new(target, data)
    if source.read_bytes() != data:
        return target, False  # changed after it was sent: keep it for the engineer
    source.unlink()
    return target, True


def show_reply(status: dict, draft, target: Path, request: Path, status_path: Path, source: Path, moved: bool) -> None:
    """Print the outcome, the rules, and where every record is."""
    reply = draft.reply
    print(f"\n{OUTCOMES[reply['outcome']]}")
    if reply.get("reason"):
        print(f"  Reason: {reply['reason']}")
    for rule in reply.get("rules") or []:
        print(f"  Rule: {rule.get('env_site')} {rule.get('spoke')} {rule.get('name')}: {rule.get('protocol')} "
              f"{', '.join(map(str, rule.get('ports') or []))} from {', '.join(map(str, rule.get('sources') or []))} "
              f"to {', '.join(map(str, rule.get('destinations') or []))}"
              + (f", translated to {rule.get('translated_address')}:{rule.get('translated_port')}"
                 if "translated_address" in rule else ""))
    used = status["used"]
    print(f"  Response: {status['response_id']}")
    print(f"  Snapshot commit: {used['commit']}")
    print(f"  Agent: {agent_code.AGENT_NAME} v{used['agent_version']}, definition {used['definition_sha']}")
    print(f"  Used = verified: {'yes' if status['used_matches_verified'] else 'NO, compare the two in the record'}")
    print(f"  Tokens: {status.get('input_tokens')} in, {status.get('output_tokens')} out; "
          f"tool calls: {len(status.get('tools') or [])}")
    print(f"  Draft branch (local, nothing written): {draft.branch}")
    print("Files:")
    print(f"  {target.relative_to(DEMO)}  (the ticket, exactly as sent)")
    print(f"  {request.relative_to(DEMO)}  (the request sent to Foundry)")
    print(f"  {status_path.relative_to(DEMO)}  (verification, acceptance, IDs, reply and result)")
    if not moved:
        print(f"  NOTE: {source.relative_to(DEMO)} changed after it was sent, so it was kept; compare the two files.")
    print("No rule file was written. Nothing was committed, pushed or applied.")


# ------------------------------------------------------------------ the flow


def main(argv: list[str] | None = None) -> int:
    """Check the ticket, verify main, ask, then accept, record, send once, save the result and move the ticket."""
    parser = argparse.ArgumentParser(description="Verify GitHub main in Azure, then send one demo ticket to Foundry.")
    parser.add_argument("--approve-prune", action="store_true",
                        help="allow a sync to delete snapshots replaced more than 24 hours ago (as in step 3)")
    args = parser.parse_args(argv)
    number = TICKET_NUMBER

    print("== Checking the ticket ==")
    try:
        source, data, ticket, owner, repo_id = check_ticket(number)
        os.environ["FWAGENT_PROJECT_ENDPOINT"] = verification.endpoint()
    except Stopped as error:
        print(f"Stopped before anything was recorded or sent: {error}")
        return NOT_SENT
    except Exception as error:  # the endpoint read: sign-in or Terraform problems
        print(f"Stopped before anything was recorded or sent: the Foundry endpoint could not be read: "
              f"{type(error).__name__}: {error}")
        return NOT_SENT
    print(f"{number}: ticket, branch, intake and lifecycle checks passed.\n")

    outcome = verification.checked(REPO, args.approve_prune)  # step 3's six checks, and its sync if you approve
    verified = outcome.verified
    if outcome.code != verification.READY or verified is None:
        print("\nStopped: verification did not pass, so nothing was accepted or sent. The ticket stays in 01-waiting.")
        return NOT_SENT

    version = ticket_version(ticket)
    show_summary(number, ticket, version, verified)
    if not verification.interactive():
        print("\nNot asked: this is not an interactive terminal. Nothing was accepted or sent.")
        return NOT_SENT
    if verification.ask(SEND_QUESTION).strip().lower() not in ("y", "yes"):
        print("Not sent. Nothing was accepted or recorded; the ticket stays in 01-waiting.")
        return NOT_SENT
    try:
        recheck(source, data, verified)
    except Stopped as error:
        print(f"Stopped before anything was recorded or sent: {error}")
        return NOT_SENT

    review = acceptance(version, ENGINEER, REASON)
    payload = message(ticket, review)  # the exact text the agent receives (workflow/agent.py message)
    request, status_path = SUBMIT / f"{number}.json", SUBMIT / f"{number}.status.json"
    status = {"number": number, "ticket_version": version, "ticket_sha256": sha256(data), "agent": agent_code.AGENT_NAME,
              "engineer": ENGINEER, "reason": REASON, "review": review, "payload_sha256": sha256(payload.encode()),
              "verified": verified.record(), "verified_main_commit": verified.commit,
              "verified_agent_version": verified.agent_version, "verified_definition_sha": verified.definition_sha,
              "ticket_file": str(source.relative_to(DEMO)), "write_status": "not_written",
              "write_reason": "step 4 saves the reply only; no rule file is written", "sent_at": now(),
              "foundry_status": "sending"}
    lifecycle.register(state_dir(REPO), number, owner, repo_id)  # one unfinished ticket per engineer
    write_new(request, payload.encode())
    write_json(status_path, status)  # if this script dies mid-call, the file still says the result is unknown
    print(f"\nAccepted {number} version {version[:12]} for {ENGINEER}.")
    print(f"Saved request {request.relative_to(DEMO)}")

    if source.read_bytes() != data:
        status = status | {"foundry_status": "not_sent", "failure": "the ticket file changed after it was accepted",
                           "finished_at": now()}
        write_json(status_path, status)
        print(f"Stopped: {source.name} changed after it was accepted. Nothing was sent; the ticket stays in 01-waiting.")
        return NOT_SENT

    holder = Holder(verified)
    print(f"Drafting once from GitHub main {verified.commit[:12]} with {verified.agent_name} v{verified.agent_version}...")
    try:
        draft = draft_from_main(REPO, state_dir(REPO) / "worktrees", number, ticket, review, holder.make,
                                snapshot_container(), max_attempts=1)
    except BaseException as error:  # Ctrl-C included: the record must say what is known before stopping
        status, code = failed_status(status | {"would_use": holder.would_use}, error, holder.call())
        write_json(status_path, status)
        print(f"\n{status['foundry_status'].upper()}: {status['failure']}.")
        print(f"  Error: {status['error']}")
        if status.get("response_id"):
            print(f"  Response: {status['response_id']}")
        if code == UNCERTAIN:
            print("  Do not send it again. Check the Foundry project's traces for this ticket first.")
        print(f"  Ticket kept: {source.relative_to(DEMO)}")
        print(f"  Records: {request.relative_to(DEMO)}, {status_path.relative_to(DEMO)}")
        print("Nothing will be resent automatically. No rule file was written.")
        if not isinstance(error, Exception):
            raise
        return code

    # From here on Foundry has answered. Nothing below may call it again, whatever fails.
    try:
        last = draft.audit["attempts"][-1]
        used = used_values(draft, holder)
        status = status | call_fields(holder.call()) | {
            "foundry_status": "succeeded", "reply": draft.reply, "main_commit": draft.commit, "snapshot": draft.commit,
            "agent_version": draft.audit["agent_version"], "used": used,
            "used_matches_verified": (used["commit"], used["agent_version"], used["definition_sha"])
            == (verified.commit, verified.agent_version, verified.definition_sha)
            and used["manifest_sha256"] == verified.manifest_sha256,
            "branch": draft.branch, "worktree": str(draft.worktree), "attempts": draft.audit["attempts"],
            "response_id": last.get("response_id"), "tool_snapshots": last.get("tool_commits"), "finished_at": now()}
        write_json(status_path, status)  # the reply is on disk before the ticket moves
    except Exception as error:
        call = holder.call()
        print(f"\nFoundry answered, but the reply could not be saved: {type(error).__name__}: {error}")
        print(f"  Response: {getattr(call, 'response_id', None)}")
        print(f"  Reply: {json.dumps(draft.reply, default=str)}")
        print(f"  Ticket kept: {source.relative_to(DEMO)}. Do not send it again; copy the reply above first.")
        return RESPONSE_UNUSABLE
    lifecycle.register(state_dir(REPO), number, owner, repo_id, branch=draft.branch, worktree=str(draft.worktree),
                       base=draft.commit)
    try:
        target, moved = move_ticket(source, data)
    except OSError as error:
        status = status | {"ticket_move_error": f"{type(error).__name__}: {error}"}
        write_json(status_path, status)
        print(f"The reply is saved in {status_path.relative_to(DEMO)}, but the ticket could not be copied to "
              f"02-submit: {error}. It stays in 01-waiting. Do not send it again.")
        return RESPONSE_UNUSABLE
    status = status | {"ticket_file": str(target.relative_to(DEMO)), "ticket_moved_at": now(),
                       "original_kept": not moved}
    write_json(status_path, status)
    try:
        show_reply(status, draft, target, request, status_path, source, moved)
    except Exception as error:  # showing it is not part of the result; the record is already complete
        print(f"\nThe reply is saved in {status_path.relative_to(DEMO)}, but it could not be shown: {error}")
    return REPLY_SAVED


if __name__ == "__main__":
    raise SystemExit(main())
