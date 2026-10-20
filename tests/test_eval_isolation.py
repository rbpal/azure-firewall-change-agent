"""Keeps the test split's answers away from the agent being evaluated.

Example: if a runbook gains RITM0012021 as a worked example, or a tool imports
from evals/, these tests fail.
Why: the agent's prompts, examples and retrieval context come from the repo
(runbooks, standards, network data, agent code). A test ticket that leaks into
any of them lets the agent see the answer it is scored on.
Safety rule: test-split tickets live only in evals/requests/test/; only the
runner, which refuses the test split unless asked, and tests may read them.
"""

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
TEST_SPLIT = REPO / "evals" / "requests" / "test"
# Code the agent runs or reads: its tools, the workflow around it, its prompts.
AGENT_SIDE = ["agents", "mcp", "workflow", "policy"]
# Folders allowed to hold test-split tickets or their numbers.
ALLOWED = ("evals/", "tests/")


def split_numbers() -> set[str]:
    """The ticket numbers of every test-split request, from the file names."""
    return {p.stem.removeprefix("test_") for p in TEST_SPLIT.glob("test_RITM*.yaml")}


def tracked_files() -> list[str]:
    """Every file git tracks, as repo-relative paths."""
    out = subprocess.run(["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True)
    return out.stdout.splitlines()


def test_the_test_split_is_not_empty():
    """The number check below means nothing if no test tickets are found."""
    assert len(split_numbers()) >= 20


def test_no_test_ticket_number_outside_evals_and_tests():
    """No runbook, standard, data file, prompt or code names a test-split ticket."""
    numbers = split_numbers()
    leaks = []
    for rel in tracked_files():
        if rel.startswith(ALLOWED):
            continue
        path = REPO / rel
        try:
            text = path.read_text()
        except (UnicodeDecodeError, FileNotFoundError):
            continue
        leaks += [f"{rel}: {n}" for n in numbers if n in text]
    assert leaks == []


@pytest.mark.parametrize("folder", AGENT_SIDE)
def test_agent_side_code_never_reads_evals(folder):
    """Agent tools, workflow and prompts never import or open anything under evals/."""
    hits = []
    for path in sorted((REPO / folder).rglob("*")):
        if path.is_file() and path.suffix in {".py", ".md", ".yaml", ".yml", ".json", ".txt"}:
            for n, line in enumerate(path.read_text().splitlines(), 1):
                if re.search(r"\bevals\b", line):
                    hits.append(f"{path.relative_to(REPO)}:{n}")
    assert hits == []
