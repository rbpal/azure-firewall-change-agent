"""Create the local demo branch for one ticket, from the latest GitHub main.

Example: set TICKET_NUMBER = "RITM0013004" below, then run
    uv run python demo/scripts/step_02_create_branch_for_demo_ticket.py
It creates and switches to demo/RITM0013004 at origin/main, without tracking main.

Why: each demo ticket gets its own branch, started from exactly the main that Azure's snapshot holds,
so the draft and its review never mix in another ticket's changes.

Safety rule: it only fetches, checks and creates one branch. It stops if the ticket file is missing, the working
tree has changes, HEAD is not origin/main, or the branch already exists while another branch is checked out. It
never deletes branches, resets files, stashes, commits, pushes, merges or applies anything.
"""

# =====================================================================================
#  CHANGE THIS FOR EACH NEW TICKET. This is the only line you edit.
# =====================================================================================
TICKET_NUMBER = "RITM0013525"

# =====================================================================================
#  FIXED SETTINGS. Do not change these for a normal demo run.
#  The branch name is built for you: BRANCH_PREFIX + TICKET_NUMBER -> demo/RITM0013004
# =====================================================================================
BRANCH_PREFIX = "demo/"                       # every demo branch name starts with this
WAITING_FOLDER = "demo/01-waiting"  # where step 1 writes the ticket, from the repo's top folder
REMOTE = "origin"                             # the GitHub remote
MAIN_BRANCH = "main"                          # every demo branch starts from REMOTE/MAIN_BRANCH
TICKET_PATTERN = r"RITM\d{7}"                 # a ticket number is RITM followed by 7 digits
# =====================================================================================

import re  # noqa: E402
import subprocess  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[2]  # found from this file's place: <repo>/demo/scripts/
WAITING = Path(WAITING_FOLDER)
NUMBER = re.compile(TICKET_PATTERN)
UPSTREAM = f"{REMOTE}/{MAIN_BRANCH}"  # origin/main


class Stop(Exception):
    """A reason to stop with nothing changed, in plain words."""


def git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run git in repo, wherever this script is started from; a failure stops with git's message when check is on."""
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    if check and done.returncode != 0:
        raise Stop(f"git {' '.join(args)} failed: {done.stderr.strip()}")
    return done


def out(repo: Path, *args: str) -> str:
    """Run git in repo and return its trimmed output."""
    return git(repo, *args).stdout.strip()


def exists(repo: Path, ref: str) -> bool:
    """Whether a Git reference, such as refs/heads/demo/RITM0013004, exists."""
    return git(repo, "rev-parse", "--verify", "--quiet", ref, check=False).returncode == 0


def branch_for(number: str) -> str:
    """The demo branch name for a ticket number, e.g. RITM0013004 -> demo/RITM0013004."""
    if not NUMBER.fullmatch(number or ""):
        raise Stop(f"TICKET_NUMBER is {number!r}; it must be RITM followed by 7 digits, e.g. RITM0013004")
    return f"{BRANCH_PREFIX}{number}"


def run(repo: Path, number: str) -> int:
    """Check the ticket and working tree, fetch the remote, then create the ticket branch or report it; 0 when done."""
    branch = branch_for(number)
    top = Path(out(repo, "rev-parse", "--show-toplevel")).resolve()
    if top != Path(repo).resolve():
        raise Stop(f"{repo} is not the top of a Git repository (the top is {top})")
    ticket = Path(repo) / WAITING / f"{number}.yaml"
    if not ticket.is_file():
        raise Stop(f"the ticket {WAITING / (number + '.yaml')} does not exist")
    print(f"Ticket found: {WAITING / (number + '.yaml')}")
    dirty = out(repo, "status", "--short")
    if dirty:
        raise Stop("the working tree has uncommitted changes. Commit or move them yourself, then run this "
                   "again:\n" + dirty)
    print("Working tree: clean")
    git(repo, "fetch", REMOTE)
    main = out(repo, "rev-parse", UPSTREAM)
    head = out(repo, "rev-parse", "HEAD")
    current = out(repo, "rev-parse", "--abbrev-ref", "HEAD")
    print(f"Fetched {REMOTE}. {UPSTREAM} is {main[:12]}.")

    if current == branch:
        where = f"the same as {UPSTREAM}" if head == main else f"not {UPSTREAM} ({main[:12]})"
        print(f"Already on {branch} at {head[:12]}, {where}. Nothing was changed.")
        return 0
    if exists(repo, f"refs/heads/{branch}"):
        raise Stop(f"{branch} already exists, but {current} is checked out. This script does not switch to or "
                   f"change an existing branch. Check what is on it with: git log --oneline -3 {branch}")
    if exists(repo, f"refs/remotes/{REMOTE}/{branch}"):
        raise Stop(f"GitHub already has a branch named {branch}. A new local branch with that name would differ from "
                   "it. Decide what to do with the GitHub branch first.")
    if head != main:
        raise Stop(f"HEAD ({current} at {head[:12]}) is not {UPSTREAM} ({main[:12]}). Bring {current} up to date or "
                   f"check out {MAIN_BRANCH} yourself, then run this again.")

    git(repo, "checkout", "--no-track", "-b", branch, UPSTREAM)
    now = out(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if now != branch or out(repo, "rev-parse", "HEAD") != main:
        raise Stop(f"after creating {branch}, HEAD is {now}; check with git status")
    print(f"Created and switched to {branch} at {main[:12]} ({UPSTREAM}), not tracking {MAIN_BRANCH}.")
    print("Not pushed. Nothing was committed, merged or applied.")
    return 0


def main() -> int:
    """Run the branch step for the configured ticket number and print why it stopped, if it did."""
    try:
        return run(REPO, TICKET_NUMBER)
    except Stop as reason:
        print(f"Stopped: {reason}")
        print("Nothing was changed.")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
