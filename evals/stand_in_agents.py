"""Stand-in agents: practice students for the Tier 2 runner, with fixed answers and no model.

Example: `perfect(answers)` returns an agent that answers RITM0011001 with the
two labelled sftp rules, copied from the answer key. `always_stop` answers every
ticket with stop_and_ask, reason free_text_conflict.

Why: the runner must be checked before a real agent exists. The perfect agent
must score every validation ticket passed and complete, so any shortfall is a runner or scorer
bug. The always-stop agent gives the always-stop baseline, a reference point and
not a floor.

Safety rule: the perfect agent gets the answer keys when it is built, never
through the runner, so the runner itself never hands a key to any agent.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Callable

Agent = Callable[..., dict]  # agent(ticket), plus engineer_review=... and dns_lookup=... when the request has them

# The boxes of a reply: the same names as in an `expected:` answer key, without
# the label's own notes (labelled_against, note, tools).
REPLY_KEYS = ("outcome", "reason", "action", "rules")


STUB_ADDRESSES = ["192.0.2.80", "192.0.2.81"]  # documentation range: what the stand-in's DNS "returns" for any FQDN


@dataclass
class StubCall:
    """The one thing the runner reads from a stand-in's call: the DNS answers it saw."""

    dns_answers: list[dict] = field(default_factory=list)
    tool_calls: list[dict] | None = None
    tools: list[str] = field(default_factory=list)
    input_tokens: int = 0
    output_tokens: int = 0


def with_fqdn_destinations(expected: dict) -> dict:
    """A copy of a label as a reply would carry it: each destinations_from_dns becomes the FQDN as the destination."""
    out = copy.deepcopy(expected)
    for rule in out.get("rules") or []:
        if "destinations_from_dns" in rule:
            rule["destinations"] = [rule.pop("destinations_from_dns")]
    return out


def perfect(answers: dict[str, dict]) -> Agent:
    """Build an agent that answers each ticket with its labelled answer, keyed by ticket number."""
    keys = copy.deepcopy(answers)

    def agent(ticket: dict, engineer_review: dict | None = None, dns_lookup=None) -> dict:
        """Return the labelled answer for this ticket, in reply shape; a DNS-checked FQDN becomes the destination."""
        expected = keys[ticket["number"]]
        reply = {k: copy.deepcopy(expected[k]) for k in REPLY_KEYS if k in expected}
        hosts = set()
        for rule in reply.get("rules") or []:
            if "destinations_from_dns" in rule:
                hosts.add(rule["destinations_from_dns"])
                rule["destinations"] = [rule.pop("destinations_from_dns")]
        if hosts:  # only a DNS ticket records a call, so every other ticket is scored exactly as before
            agent.calls.append(StubCall([{"host": h, "resolves": True, "a": list(STUB_ADDRESSES)} for h in sorted(hosts)]))
        return reply

    agent.calls = []
    return agent


def always_stop(ticket: dict, engineer_review: dict | None = None, dns_lookup=None) -> dict:
    """Stop and ask on every ticket, always with the same reason."""
    return {"outcome": "stop_and_ask", "reason": "free_text_conflict", "rules": []}
