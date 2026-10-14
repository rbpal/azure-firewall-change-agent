"""Mutation test for the two eval scorers: break each one on purpose and check a test notices.

Example: `uv run --python 3.11 python evals/mutate_scorers.py` prints one line per
mutation, such as "caught    widen a port range", and exits 1 if any survives.

Why: the scorers grade the agent before any Foundry spend. If the tests still pass
when a scorer is broken, a weak agent could pass too, so CI runs this on every push.

Safety rule: each mutation edits a scorer file in place and the original is always
written back, even on error. It runs only the scorer tests in tests/evals/.
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LP = "evals/least_privilege.py"
AB = "evals/abstention.py"


@dataclass(frozen=True)
class Mutation:
    """One deliberate break: in this file, replace old text with new text."""

    name: str
    path: str
    old: str
    new: str


MUTATIONS = [
    # Least-Privilege: the ways a scorer could let a wider draft through.
    Mutation("widen a port range", LP, "a[0] <= r[0] and r[1] <= a[1]", "a[0] <= r[0]"),
    Mutation("drop the protocol comparison", LP,
             'if str(rule.get("protocol", "")).upper() != label["protocol"].upper():', "if False:"),
    Mutation("accept a wider address", LP, "net.subnet_of(other)", "(other.subnet_of(net) or net.subnet_of(other))"),
    Mutation("drop the DNAT translation comparison", LP, "if str(rule.get(f)) != str(label.get(f)):", "if False:"),
    Mutation("accept any hostname or IP group", LP, "if _plain(value) in {_plain(a) for a in approved}:", "if True:"),
    Mutation("read '*' as port 22 only", LP, "return ALL_PORTS", "return (22, 22)"),
    Mutation("never fail on excess", LP, '    if score.excess:\n        score.result = "fail"', "    pass"),
    Mutation("fail on incomplete too", LP, "    if score.excess:\n", "    if score.excess or score.incomplete:\n"),
    Mutation("approve rules when the label writes none", LP,
             'expected["rules"] if expected["outcome"] == "draft" else []', 'expected["rules"]'),
    Mutation("stop reporting missing rules", LP, 'score.incomplete.append(f"{_name(key)}: rule missing")', "pass"),
    Mutation("stop reporting narrower ranges", LP,
             "covered = any(net.subnet_of(n) for n in nets)", "covered = any(n.subnet_of(net) for n in nets)"),
    Mutation("keep the trailing dot on names", LP, 'return value.strip().lower().rstrip(".")', "return value.strip().lower()"),
    Mutation("allow two label rules per key", LP,
             '            raise ValueError(f"label has two rules for {_name(_key(rule))}")', "            pass"),
    # Removals: anything but the exact labelled rules must fail.
    Mutation("ignore a rule left in place", LP, "for k in want.keys() - got.keys()]", "for k in []]"),
    Mutation("ignore an extra rule removed", LP, "for k in got.keys() - want.keys()]", "for k in []]"),
    Mutation("ignore a changed field on removal", LP, "if _exact(want[k].get(f)) != _exact(got[k].get(f))]", "if False]"),
    Mutation("ignore add versus remove", LP, 'if expected.get("action") != reply.get("action"):', "if False:"),
    # Abstention: the ways a scorer could reward a guess.
    Mutation("accept a guess as an answer", AB, 'return Score("fail", "missed_stop"', 'return Score("pass", "missed_stop"'),
    Mutation("ignore the stop reason", AB, 'if reply.get("reason") != expected["reason"]:', "if False:"),
    Mutation("allow rules on a stop", AB, 'if reply.get("rules"):', "if False:"),
    Mutation("accept a needless stop", AB, 'return Score("fail", "over_abstain"', 'return Score("pass", "over_abstain"'),
    Mutation("treat any non-draft as a stop", AB, 'stopped = reply.get("outcome") == STOP', 'stopped = reply.get("outcome") != "draft"'),
]
# Not listed: removing the 1-65535 port bounds. An out-of-range port is already
# outside every approved range, so no score can change; that mutant is equivalent.


@contextmanager
def mutated(path: Path, old: str, new: str):
    """Swap old text for new in a file for the length of a with-block, then put the original back."""
    original = path.read_text()
    if original.count(old) != 1:
        raise ValueError(f"{path.name}: expected the text once, found {original.count(old)}: {old!r}")
    path.write_text(original.replace(old, new))
    try:
        yield
    finally:
        path.write_text(original)


def tests_pass() -> bool:
    """Run the scorer tests in a fresh process with a fresh bytecode cache; True if all pass."""
    with tempfile.TemporaryDirectory() as cache:  # a stale .pyc must never hide a mutation
        env = dict(os.environ, PYTHONPYCACHEPREFIX=cache)
        cmd = [sys.executable, "-m", "pytest", "-q", "-x", "-p", "no:cacheprovider", "tests/evals"]
        try:
            run = subprocess.run(cmd, cwd=REPO, env=env, capture_output=True, stdin=subprocess.DEVNULL, timeout=300)
        except subprocess.TimeoutExpired:
            return False
    return run.returncode == 0


def main() -> int:
    """Run every mutation; exit 1 if the tests fail unmutated or any mutation survives."""
    if not tests_pass():
        print("the scorer tests fail before any mutation; fix them first")
        return 1
    survived = []
    for m in MUTATIONS:
        with mutated(REPO / m.path, m.old, m.new):
            caught = not tests_pass()
        print(f"{'caught  ' if caught else 'SURVIVED'}  {m.name}  ({m.path})")
        if not caught:
            survived.append(m.name)
    print(f"{len(MUTATIONS) - len(survived)}/{len(MUTATIONS)} mutations caught")
    return 1 if survived else 0


if __name__ == "__main__":
    sys.exit(main())
