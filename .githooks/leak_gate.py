#!/usr/bin/env python3
"""Leak gate: stop real company data reaching this public repo.

Blocks a commit or push whose added lines, file names or commit messages
contain:

1. any term from the local block list (real company, partner and app names,
   real address prefixes, subscription and tenant IDs), and
2. any GUID other than the all-zero one, and any email address outside the
   reserved example domains.

The block list lives outside the repo, so it can never be committed:
    ~/.config/leak-gate/terms.txt   (or the path in $LEAK_GATE_TERMS)
One term per line; lines starting with # are comments. If the list is
missing or empty, the gate fails closed.

`.gitignore` is the one file allowed to name private things, so block-list
terms are not checked there. GUIDs and emails still are.

A hit is reported by file, line and term number, never by the term itself,
so the real value does not end up in terminal logs.

Modes:
    leak_gate.py --staged          pre-commit: the staged changes
    leak_gate.py --push            pre-push: reads git's ref lines on stdin
    leak_gate.py --all             every tracked file, as it is now
    leak_gate.py --history         every commit's added lines and message
Standard library only, so it runs without the project's virtualenv.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

ZERO_SHA = "0" * 40
GUID = re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b")
ZERO_GUID = "00000000-0000-0000-0000-000000000000"
EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@([A-Za-z0-9-]+\.)+[A-Za-z]{2,}\b")
GITIGNORE = re.compile(r"(^|\s)\.gitignore(:\d+)?$")
EMAIL_OK = re.compile(r"@(([A-Za-z0-9-]+\.)*example(\.(com|org|net))?|users\.noreply\.github\.com)$", re.I)


def terms_path() -> Path:
    return Path(os.environ.get("LEAK_GATE_TERMS", Path.home() / ".config" / "leak-gate" / "terms.txt"))


def load_terms() -> list[str]:
    path = terms_path()
    if not path.is_file():
        sys.exit(f"leak gate: block list not found at {path}. Create it before committing.")
    terms = [t.strip() for t in path.read_text().splitlines()]
    terms = [t for t in terms if t and not t.startswith("#")]
    if not terms:
        sys.exit(f"leak gate: block list at {path} is empty. Add the real terms before committing.")
    return terms


def term_pattern(term: str) -> re.Pattern:
    """Match a term case-insensitively, as a whole word wherever its edge is a
    letter or digit. So `zqxw` misses `zqxwy`, but `10.42.` still hits `10.42.1.0/24`."""
    left = r"(?<![A-Za-z0-9])" if term[0].isalnum() else ""
    right = r"(?![A-Za-z0-9])" if term[-1].isalnum() else ""
    return re.compile(left + re.escape(term) + right, re.I)


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout


def added_lines(diff: str):
    """(file, line text) for every added line in a unified diff, plus each new file's path."""
    current = "?"
    for line in diff.splitlines():
        if line.startswith("+++ "):
            current = line[6:] if line.startswith("+++ b/") else line[4:]
            yield current, current  # the path itself can leak
        elif line.startswith("+") and not line.startswith("+++"):
            yield current, line[1:]


def scan(items, terms) -> list[str]:
    patterns = [term_pattern(t) for t in terms]
    hits = []
    for where, text in items:
        for n, p in enumerate([] if GITIGNORE.search(where) else patterns, start=1):
            if p.search(text):
                hits.append(f"{where}: block-list term #{n}")
        for g in GUID.findall(text):
            if g != ZERO_GUID:
                hits.append(f"{where}: a GUID")
        for m in EMAIL.finditer(text):
            if not EMAIL_OK.search(m.group(0)):
                hits.append(f"{where}: an email address")
    return sorted(set(hits))


def staged_items():
    yield from added_lines(git("diff", "--cached", "--no-color", "-U0"))


def push_items(stdin: str):
    for line in stdin.splitlines():
        parts = line.split()
        if len(parts) != 4 or parts[1] == ZERO_SHA:
            continue  # malformed, or a branch delete
        local_sha, remote_sha = parts[1], parts[3]
        if remote_sha == ZERO_SHA:
            commits = git("rev-list", local_sha, "--not", "--remotes").split()
        else:
            commits = git("rev-list", f"{remote_sha}..{local_sha}").split()
        for c in commits:
            yield f"commit {c[:7]} message", git("log", "-1", "--format=%B", c)
            yield from ((f"commit {c[:7]} {f}", t) for f, t in added_lines(git("show", "--format=", "--no-color", "-U0", c)))


def all_items():
    for f in git("ls-files", "-z").split("\0"):
        if not f:
            continue
        yield f, f
        try:
            text = Path(f).read_text()
        except (UnicodeDecodeError, FileNotFoundError, IsADirectoryError):
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            yield f"{f}:{i}", line


def history_items():
    for c in git("rev-list", "--all").split():
        yield f"commit {c[:7]} message", git("log", "-1", "--format=%B", c)
        yield from ((f"commit {c[:7]} {f}", t) for f, t in added_lines(git("show", "--format=", "--no-color", "-U0", c)))


def main(argv: list[str]) -> int:
    mode = argv[1] if len(argv) > 1 else "--staged"
    terms = load_terms()
    items = {
        "--staged": staged_items,
        "--push": lambda: push_items(sys.stdin.read()),
        "--all": all_items,
        "--history": history_items,
    }.get(mode)
    if items is None:
        sys.exit(f"leak gate: unknown mode {mode}")
    hits = scan(items(), terms)
    if hits:
        print("leak gate: BLOCKED. Real data found:", file=sys.stderr)
        for h in hits:
            print(f"  {h}", file=sys.stderr)
        print(f"Terms are numbered by line order in {terms_path()} (comments and blanks skipped).", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
