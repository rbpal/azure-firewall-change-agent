"""Stand-in agents: practice students for the Tier 2 runner, with fixed answers and no model.

Example: `perfect(answers)` returns an agent that answers RITM0011001 with the
two labelled sftp rules, copied from the answer key. `always_stop` answers every
ticket with stop_and_ask, reason free_text_conflict.

Why: the runner must be checked before a real agent exists. The perfect agent
must score 40 of 40 passed and complete, so any shortfall is a runner or scorer
bug. The always-stop agent gives the always-stop baseline, a reference point and
not a floor.

Safety rule: the perfect agent gets the answer keys when it is built, never
through the runner, so the runner itself never hands a key to any agent.
"""

from __future__ import annotations

import copy
from typing import Callable

Agent = Callable[[dict], dict]

# The boxes of a reply: the same names as in an `expected:` answer key, without
# the label's own notes (labelled_against, note, tools).
REPLY_KEYS = ("outcome", "reason", "action", "rules")


def perfect(answers: dict[str, dict]) -> Agent:
    """Build an agent that answers each ticket with its labelled answer, keyed by ticket number."""
    keys = copy.deepcopy(answers)

    def agent(ticket: dict) -> dict:
        """Return the labelled answer for this ticket, in reply shape."""
        expected = keys[ticket["number"]]
        return {k: copy.deepcopy(expected[k]) for k in REPLY_KEYS if k in expected}

    return agent


def always_stop(ticket: dict) -> dict:
    """Stop and ask on every ticket, always with the same reason."""
    return {"outcome": "stop_and_ask", "reason": "free_text_conflict", "rules": []}
