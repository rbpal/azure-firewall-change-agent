"""Step 9: archive a finished ticket's files, then remove everything else left over from it.

Example: with the settings below,
    uv run python demo/scripts/step_09_archive_ticket.py
checks on GitHub that the pull request from demo/RITM0013201 is merged, then creates
04-archive/<NNN>-2026-11-08-RITM0013201-sett-to-apisecgov-https443/ and moves into it every file in 02-submit/ and
03-pr-description/pr-description-RITM0013201.md. NNN is one more than the highest NNN- folder already in 04-archive.
Then it lists the ticket's leftovers (the agent's register entry, its worktree, the local demo/ and agent/ branches,
and the branch on GitHub) and removes them after you type y.

Why: once a ticket is merged and applied, its records belong together in one archive folder, and its branches and
register entry only add noise. A leftover register entry also blocks step 4 for the next ticket.

Safety rule: nothing is moved or removed unless GitHub says the pull request is merged. Nothing is removed if a
worktree holds any uncommitted, untracked or ignored file, if a branch holds a commit that is not on origin/main, or
if this checkout is on one of the ticket's branches. Git does the removals without force. Git history, the pull
request on GitHub and the archive folder are kept.
"""

# =====================================================================================
#  SETTINGS. Change these for each ticket you archive.
# =====================================================================================
TICKET_NUMBER = "RITM0013525"
CLOSURE_DATE = "2026-11-24"
SHORT_DESCRIPTION = "rprt-to-wikipedia-tcp443"
DEMO_ROOT = "demo"
REMOTE = "origin"
# =====================================================================================

import re  # noqa: E402
import shutil  # noqa: E402
import sys  # noqa: E402
from pathlib import Path  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from workflow import lifecycle  # noqa: E402
from workflow.cli import state_dir  # noqa: E402

gh = lifecycle.run_gh  # the GitHub command line; tests replace it


def ticket_branch(name: str, number: str) -> bool:
    """Whether a branch is exactly this ticket's demo/ branch or one of its agent/ draft branches."""
    return name == "demo/" + number or bool(re.fullmatch(rf"agent/{number}-[0-9a-f]{{7,40}}", name))


def git(*args: str) -> str:
    """Run git in the repository and return its trimmed output; a failure raises lifecycle.Unverified."""
    return lifecycle.git(REPO, *args).strip()


def next_number(archive: Path) -> str:
    """One more than the highest NNN- archive folder, as 3 digits; 001 when there is none."""
    used = [int(m.group(1)) for p in archive.iterdir() if p.is_dir() and (m := re.match(r"(\d{3})-", p.name))]
    return f"{max(used, default=0) + 1:03d}"


def merge_problem(number: str) -> str | None:
    """Why the ticket's pull request does not count as merged, or None when GitHub says it is merged."""
    branch = f"demo/{number}"
    try:
        pr = lifecycle.pr_for(lifecycle.repo_id(REPO), branch, gh)
    except lifecycle.Unverified as error:
        return f"GitHub could not be checked ({error})"
    if not pr:
        return f"GitHub has no pull request from {branch}"
    if pr.get("state") != "MERGED":
        return f"pull request #{pr.get('number')} from {branch} is {str(pr.get('state')).lower()}, not merged"
    return None


def archive_files(demo: Path, number: str) -> int:
    """Move the ticket's files into a new numbered archive folder; 0 when done or already archived, 1 when stopped."""
    archive = demo / "04-archive"
    files = sorted(p for p in (demo / "02-submit").iterdir() if p.is_file() and not p.name.startswith("."))
    pr = demo / "03-pr-description" / f"pr-description-{number}.md"
    if pr.is_file():
        files.append(pr)
    if not files:
        earlier = sorted(archive.glob(f"[0-9][0-9][0-9]-*-{number}-*"))
        if earlier:
            print(f"Already archived in {earlier[-1].relative_to(demo)}/")
            return 0
        print("Stopped: no files to move and no archive folder for this ticket. Nothing was created.")
        return 1
    folder = archive / f"{next_number(archive)}-{CLOSURE_DATE}-{number}-{SHORT_DESCRIPTION}"
    if folder.exists():
        print(f"Stopped: {folder} already exists. Nothing was moved.")
        return 1
    folder.mkdir(parents=True)
    for path in files:
        shutil.move(str(path), str(folder / path.name))
        print(f"Moved {path.relative_to(demo)} -> {folder.relative_to(demo)}/{path.name}")
    print(f"Done: {len(files)} file(s) in {folder.relative_to(demo)}/")
    return 0


def leftovers(number: str) -> dict:
    """The ticket's register entry, worktrees, local branches and branches on GitHub that still exist."""
    entry = lifecycle.register_dir(state_dir(REPO)) / f"{number}.json"
    found = {"entry": entry if entry.is_file() else None, "worktrees": [], "branches": [], "remote": []}
    for block in git("worktree", "list", "--porcelain").split("\n\n"):
        fields = dict(line.split(" ", 1) if " " in line else (line, "") for line in block.splitlines())
        branch = (fields.get("branch") or "").removeprefix("refs/heads/")
        path = fields.get("worktree")
        if path and Path(path).resolve() != REPO.resolve() and ticket_branch(branch, number):
            found["worktrees"].append((Path(fields["worktree"]), branch))
    for name in git("for-each-ref", "--format=%(refname:short)", "refs/heads/").splitlines():
        if ticket_branch(name, number):
            found["branches"].append(name)
    for name in git("for-each-ref", "--format=%(refname:short)", f"refs/remotes/{REMOTE}/").splitlines():
        if ticket_branch(name.removeprefix(f"{REMOTE}/"), number):
            found["remote"].append(name.removeprefix(f"{REMOTE}/"))
    return found


def blockers(found: dict) -> list[str]:
    """Every reason removing the leftovers could lose work: changed files, unmerged commits, this checkout on them."""
    problems = []
    current = git("rev-parse", "--abbrev-ref", "HEAD")
    if current in found["branches"]:
        problems.append(f"this checkout is on {current}; switch to main first (step 9)")
    for path, _ in found["worktrees"]:
        if not path.is_dir():
            problems.append(f"worktree {path} is missing on disk; check it, then run git worktree prune yourself")
            continue
        changed = lifecycle.git(path, "status", "--porcelain", "--untracked-files=all", "--ignored").splitlines()
        if changed:
            problems.append(f"worktree {path} holds {len(changed)} uncommitted, untracked or ignored file(s): "
                            + ", ".join(line[3:] for line in changed[:5]))
    refs = found["branches"] + [f"{REMOTE}/{name}" for name in found["remote"]]
    for ref in refs:
        commits = git("log", "--format=%h %s", f"{REMOTE}/main..{ref}").splitlines()
        if commits:
            problems.append(f"{ref} has {len(commits)} commit(s) not on {REMOTE}/main: " + "; ".join(commits[:5]))
    return problems


def show(found: dict) -> None:
    """Print each leftover that will be removed."""
    print("\nLeft over from this ticket:")
    if found["entry"]:
        print(f"  register entry  {found['entry']}")
    for path, branch in found["worktrees"]:
        print(f"  worktree        {path} ({branch})")
    for name in found["branches"]:
        print(f"  local branch    {name}")
    for name in found["remote"]:
        print(f"  GitHub branch   {REMOTE}/{name}")


def remove(found: dict) -> None:
    """Remove the worktrees, local branches, register entry and GitHub branches, without force."""
    for path, _ in found["worktrees"]:
        git("worktree", "remove", str(path))
        print(f"Removed worktree {path}")
    for name in found["branches"]:
        git("branch", "-d", name)
        print(f"Deleted local branch {name}")
    if found["entry"]:
        found["entry"].unlink()
        print(f"Removed register entry {found['entry']}")
    for name in found["remote"]:
        git("push", REMOTE, "--delete", name)
        print(f"Deleted GitHub branch {name}")
    git("fetch", "--prune", "--quiet", REMOTE)


def ask(question: str) -> str:
    """Ask one question at the terminal; end of input counts as no answer."""
    try:
        return input(question)
    except EOFError:
        return ""


def main() -> int:
    """Check the merge, archive the ticket's files, then remove its leftovers after a y."""
    number = TICKET_NUMBER
    if not re.fullmatch(r"RITM\d{7}", number):
        print(f"Set TICKET_NUMBER at the top first: RITM followed by 7 digits, not {number!r}. Nothing was moved.")
        return 2
    problem = merge_problem(number)
    if problem:
        print(f"Stopped: {problem}. Nothing was moved or removed.")
        return 1
    if archive_files(REPO / DEMO_ROOT, number) != 0:
        return 1
    try:
        git("fetch", "--prune", "--quiet", REMOTE)
        found = leftovers(number)
        if not (found["entry"] or found["worktrees"] or found["branches"] or found["remote"]):
            print("Nothing left over from this ticket.")
            return 0
        show(found)
        problems = blockers(found)
        if problems:
            print("\nNot removed, because removing could lose work:")
            for item in problems:
                print(f"  - {item}")
            return 1
        if ask("\nType y to remove all of these: ").strip().lower() != "y":
            print("Nothing removed.")
            return 1
        remove(found)
    except lifecycle.Unverified as error:
        print(f"Stopped: {error}. Run step 9 again after fixing it; it carries on from where it stopped.")
        return 1
    print(f"Done: nothing is left over from {number}.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
