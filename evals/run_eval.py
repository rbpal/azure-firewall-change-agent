"""Tier 2 runner: give each labelled ticket to an agent, score the reply, print a score sheet.

Example: `uv run --python 3.11 python -m evals.run_eval --agent perfect` reads the
66 validation files, hands each `ticket:` block to the perfect stand-in agent,
scores every reply against its `expected:` block and prints the sheet. A ticket
passes when the outcome word matches, Least-Privilege is pass or not_scored, and
Abstention is pass. A pass is "complete" only if the draft is not narrower than
approved.

Why: one program produces every Tier 2 number, the same way every time. It is
tested with stand-in agents before the real agent exists (Step 04 Task 03).

Safety rule: the agent receives a copy of the `ticket:` block only, never the
answer key. A request that tests the engineer-review path also carries a
`engineer_review:` block, the engineer's recorded decision; the agent gets a copy of that
too, as the workflow would give it, and still never the answer key. A request with a
`dns:` block fixes what DNS does for a named host (a timeout or SERVFAIL); the agent
gets a resolver for its DNS tool that behaves that way, never the block itself, and
every other name is NXDOMAIN, as the reserved .example names are in real DNS.
The test split is sealed: reading it needs allow_test=True. An agent
crash or a malformed reply fails that ticket as agent_error and the run goes on,
so no ticket is ever dropped from the count.
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

import dns.exception
import dns.resolver
import yaml

from evals.abstention import score_abstention
from workflow.intake import ticket_version
from evals.least_privilege import score_least_privilege
from evals.stand_in_agents import Agent, always_stop, perfect

REQUESTS = Path(__file__).resolve().parent / "requests"
sys.path.insert(0, str(REQUESTS.parents[1] / "mcp"))
from tools.dns_lookup_for_fqdn import Lookup, Reply, parse_target  # noqa: E402  (the tool's own types)

DNS_FAULTS = {  # what dnspython raises, so the tool fails exactly as it would in Azure
    "timeout": lambda: dns.exception.Timeout(),
    "servfail": lambda: dns.resolver.NoNameservers(),
}
SPLITS = ("validation", "test")
OUTCOMES = ("draft", "already_allowed", "stop_and_ask")
MISTAKES = (
    "missed_stop",
    "too_wide",
    "wrong_removal",
    "wrong_outcome",
    "over_abstain",
    "wrong_reason",
    "stop_with_rules",
    "agent_error",
)


@dataclass
class Request:
    """One labelled ticket: the question and its answer key, kept apart."""

    number: str
    category: str
    ticket: dict
    expected: dict
    engineer_review: dict | None = None  # the engineer's recorded decision, for requests that resume after review
    dns: dict | None = None  # host -> "timeout" or "servfail": what DNS does for that name in this request


@dataclass
class Verdict:
    """The three checks on one reply, and what they add up to."""

    mistakes: list[str] = field(default_factory=list)
    incomplete: list[str] = field(default_factory=list)
    detail: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        """True when no check found a mistake."""
        return not self.mistakes

    @property
    def complete(self) -> bool:
        """True when the reply passed and allows everything the label approves."""
        return self.passed and not self.incomplete


@dataclass
class TicketResult:
    """One ticket's verdict, with the outcome the label wanted and the one the agent gave."""

    number: str
    category: str
    expected_outcome: str
    reply_outcome: str
    verdict: Verdict
    label_pending: bool = False  # the answer key carries `review: pending`: not yet checked by a person
    after_review: bool = False  # the agent ran with the engineer's recorded acceptance (engineer_review)


def load_requests(split: str = "validation", allow_test: bool = False) -> list[Request]:
    """Read every labelled ticket in one split, sorted by file name."""
    if split not in SPLITS:
        raise ValueError(f"unknown split {split!r}; use one of {SPLITS}")
    if split == "test" and not allow_test:
        raise PermissionError("the test split is sealed until the final check; pass allow_test=True")
    requests = []
    for path in sorted((REQUESTS / split).glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        review = data.get("engineer_review")
        if review is not None and review.get("ticket_version") != ticket_version(data["ticket"]):
            raise ValueError(f"{path.name}: engineer_review is for another ticket version; the acceptance does not cover it")
        dns_block = data.get("dns")
        if dns_block is not None:
            hosts = _ticket_hosts(data["ticket"])
            for host, fault in dns_block.items():
                if host not in hosts or fault not in DNS_FAULTS:
                    raise ValueError(f"{path.name}: dns names {host}: {fault}; it must be a ticket hostname "
                                     f"({sorted(hosts)}) and one of {sorted(DNS_FAULTS)}")
        requests.append(Request(data["id"], data["category"], data["ticket"], data["expected"], data.get("engineer_review"),
                                dns_block))
    if not requests:
        raise FileNotFoundError(f"no labelled tickets in {REQUESTS / split}")
    return requests


def _ticket_hosts(ticket: dict) -> set[str]:
    """Every hostname the ticket names, from a URL or an FQDN, as the DNS tool reads it."""
    hosts = set()
    for entry in ticket["sources"] + ticket["destination"]:
        if "url" in entry or "fqdn" in entry:
            try:
                hosts.add(parse_target(entry.get("url") or entry["fqdn"])[0])
            except Exception:  # a wildcard or malformed name is never looked up
                continue
    return hosts


def controlled_dns(conditions: dict) -> Lookup:
    """A resolver for the DNS tool: a listed host fails as named; every other name is NXDOMAIN."""

    def lookup(host: str, rdtype: str) -> Reply:
        """Answer one query the way this request's DNS behaves."""
        if host in conditions:
            raise DNS_FAULTS[conditions[host]]()
        return Reply(rcode="NXDOMAIN")

    return lookup


def score_reply(expected: dict, reply: object) -> Verdict:
    """Run the outcome check and both scorers on one reply."""
    verdict = Verdict()
    if not isinstance(reply, dict) or reply.get("outcome") not in OUTCOMES:
        verdict.mistakes.append("agent_error")
        verdict.detail.append(f"reply is not a dict with an outcome from {OUTCOMES}")
        return verdict
    if reply["outcome"] != expected["outcome"]:
        verdict.mistakes.append("wrong_outcome")
        verdict.detail.append(f"outcome {reply['outcome']}; label says {expected['outcome']}")
    lp = score_least_privilege(expected, reply)
    if lp.result == "fail":
        verdict.mistakes.append("wrong_removal" if lp.removal_mismatch else "too_wide")
        verdict.detail += lp.excess + lp.removal_mismatch
    verdict.incomplete = list(lp.incomplete)
    ab = score_abstention(expected, reply)
    if ab.result == "fail":
        verdict.mistakes.append(ab.kind)
        verdict.detail.append(ab.detail)
    return verdict


def run(agent: Agent, split: str = "validation", allow_test: bool = False, reviewed_only: bool = False,
        token_budget: int | None = None, not_run: list | None = None, replies: list | None = None,
        skip: dict | None = None, only: set | None = None) -> list[TicketResult]:
    """Hand each ticket to the agent, score each reply, and return one result per ticket.

    reviewed_only leaves out labels still pending review. An agent with controlled_dns = False
    (its DNS tool runs in Azure) does not get requests with a dns: block. token_budget stops the
    run before a ticket once the agent's recorded tokens reach it. skip maps ticket numbers the
    caller leaves out to the reason, such as a snapshot that lacks the ticket's rule. only, when given, runs just
    those ticket numbers. Each left-out ticket is appended to not_run as (number, why), never scored and never
    written as a reply; each reply goes to replies, so nothing vanishes.
    """
    results = []
    for request in load_requests(split, allow_test):
        why = _not_run_reason(request, agent, reviewed_only, token_budget, skip or {}, only)
        if why:
            if not_run is not None:
                not_run.append((request.number, why))
            continue
        reply = None
        try:
            extra = {}
            if request.engineer_review is not None:
                extra["engineer_review"] = copy.deepcopy(request.engineer_review)
            if request.dns is not None:
                extra["dns_lookup"] = controlled_dns(request.dns)
            reply = agent(copy.deepcopy(request.ticket), **extra)
            verdict = score_reply(request.expected, reply)
            outcome = reply.get("outcome", "?") if isinstance(reply, dict) else "?"
        except Exception as error:  # a crashing agent fails its ticket, not the run
            verdict = Verdict(mistakes=["agent_error"], detail=[f"{type(error).__name__}: {error}"])
            outcome = "?"
        if replies is not None:
            replies.append({"number": request.number, "reply": reply, "mistakes": verdict.mistakes, "detail": verdict.detail})
        pending = request.expected.get("review") == "pending"
        results.append(TicketResult(request.number, request.category, request.expected["outcome"], outcome, verdict, pending,
                                    request.engineer_review is not None))
    return results


def _not_run_reason(request: Request, agent, reviewed_only: bool, token_budget: int | None, skip: dict,
                    only: set | None = None) -> str | None:
    """Why this request is left out of the run, or None to run it."""
    if only is not None and request.number not in only:
        return "not selected with --only"
    if request.number in skip:
        return skip[request.number]
    if reviewed_only and request.expected.get("review") == "pending":
        return "label pending review"
    if request.dns is not None and getattr(agent, "controlled_dns", True) is False:
        return "needs a controlled DNS answer the deployed tool cannot get"
    if token_budget is not None and _tokens(agent) >= token_budget:
        return "token budget reached"
    return None


def _tokens(agent) -> int:
    """Input plus output tokens the agent has recorded so far, or 0 for a stand-in."""
    return sum(c.input_tokens + c.output_tokens for c in getattr(getattr(agent, "inner", agent), "calls", []))


def summarise(results: list[TicketResult]) -> dict:
    """Count passes, complete and incomplete passes, and each kind of mistake."""
    counts = Counter(m for r in results for m in r.verdict.mistakes)
    return {
        "tickets": len(results),
        "passed": sum(r.verdict.passed for r in results),
        "complete": sum(r.verdict.complete for r in results),
        "incomplete": sum(r.verdict.passed and not r.verdict.complete for r in results),
        "stops": sum(r.expected_outcome == "stop_and_ask" for r in results),
        "labels_pending": sum(r.label_pending for r in results),
        "after_review": (sum(r.verdict.complete for r in results if r.after_review), sum(r.after_review for r in results)),
        "mistakes": {m: counts.get(m, 0) for m in MISTAKES},
        "by_category": _by_category(results),
    }


def _by_category(results: list[TicketResult]) -> dict[str, tuple[int, int]]:
    """Map each category to (passed and complete, tickets)."""
    table: dict[str, list[int]] = {}
    for r in results:
        row = table.setdefault(r.category, [0, 0])
        row[0] += r.verdict.complete
        row[1] += 1
    return {k: (v[0], v[1]) for k, v in sorted(table.items())}


def format_report(results: list[TicketResult], split: str, agent_name: str) -> str:
    """Render the score sheet: headline, mistake counts, categories, then one line per ticket."""
    s = summarise(results)
    n, stops = s["tickets"], s["stops"]
    m = s["mistakes"]
    lines = [
        f"Tier 2 eval · {split} split · {n} tickets · agent: {agent_name}",
        "",
        f"Passed and complete               {s['complete']:>3} / {n}",
        f"Passed but incomplete             {s['incomplete']:>3} / {n}   (allows less than approved)",
        f"Passed, either way                {s['passed']:>3} / {n}",
        *([f"Labels pending human review       {s['labels_pending']:>3} / {n}   (scored against unchecked answer keys)"]
          if s["labels_pending"] else []),
        f"First pass, passed and complete   {s['complete'] - s['after_review'][0]:>3} / {n - s['after_review'][1]}",
        f"After engineer review, passed     {s['after_review'][0]:>3} / {s['after_review'][1]}   (agent ran with the recorded acceptance)",
        "",
        f"Missed stops                      {m['missed_stop']:>3} / {stops}   (must be 0)",
        f"Too wide (least privilege fail)   {m['too_wide']:>3} / {n}",
        f"Wrong removal                     {m['wrong_removal']:>3} / {n}",
        f"Wrong outcome word                {m['wrong_outcome']:>3} / {n}",
        f"Over-abstain                      {m['over_abstain']:>3} / {n - stops}",
        f"Wrong stop reason                 {m['wrong_reason']:>3} / {stops}",
        f"Stop that wrote rules             {m['stop_with_rules']:>3} / {stops}",
        f"Agent error                       {m['agent_error']:>3} / {n}",
        "",
        "By category (passed and complete / tickets)",
    ]
    lines += [f"  {name:<40} {done:>2} / {total}" for name, (done, total) in s["by_category"].items()]
    lines += ["", "Per ticket"]
    for r in results:
        status = "PASS" if r.verdict.complete else "PASS-INCOMPLETE" if r.verdict.passed else "FAIL"
        why = ", ".join(r.verdict.mistakes + (["label pending review"] if r.label_pending else []))
        lines.append(f"  {r.number}  {r.category:<40} {r.expected_outcome:<16} {r.reply_outcome:<16} {status} {why}".rstrip())
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run one stand-in agent on one split and print the score sheet."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--agent", choices=("perfect", "always_stop", "foundry"), required=True)
    parser.add_argument("--split", choices=SPLITS, default="validation")
    parser.add_argument("--allow-test-split", action="store_true", help="unseal the test split")
    parser.add_argument("--reviewed-only", action="store_true", help="leave out labels still pending review")
    parser.add_argument("--only", nargs="+", metavar="RITM", help="run only these ticket numbers")
    parser.add_argument("--token-budget", type=int, help="stop before a ticket once this many tokens are used")
    parser.add_argument("--out", type=Path, help="write each reply and the token use to this JSON file")
    parser.add_argument("--not-run", nargs="+", default=[], metavar="RITM=WHY",
                        help="leave these tickets out, each with its reason; they are listed as not run")
    parser.add_argument("--data-diff-ok", nargs="*", default=None, metavar="PATH",
                        help="foundry: data files allowed to differ from the snapshot (each must be named)")
    args = parser.parse_args(argv)
    not_run, replies = [], []
    try:
        if args.agent == "perfect":
            keys = {r.number: r.expected for r in load_requests(args.split, args.allow_test_split)}
            agent = perfect(keys)
        elif args.agent == "foundry":
            from workflow.agent import AgentError, FoundryAgent
            try:
                agent = FoundryAgent.from_env(REQUESTS.parents[1], allowed_differences=args.data_diff_ok or [])
            except AgentError as error:
                print(f"refused: {error} (a differing data file can be named with --data-diff-ok, and each ticket "
                      "that depends on it left out with --not-run)")
                return 2
        else:
            agent = always_stop
        skip = dict(entry.split("=", 1) for entry in args.not_run)
        results = run(agent, args.split, args.allow_test_split, args.reviewed_only, args.token_budget, not_run, replies, skip,
                      set(args.only) if args.only else None)
    except PermissionError as error:
        print(f"refused: {error} (command line: --allow-test-split)")
        return 2
    report = format_report(results, args.split, args.agent)
    if not_run:
        report += "\n\nNot run\n" + "\n".join(f"  {number}  {why}" for number, why in not_run)
    inner = getattr(agent, "inner", agent)
    if getattr(inner, "snapshot", None):
        now = inner.pointer_now()
        report += f"\n\nSnapshot pinned for every tool call: {inner.snapshot}"
        if now != inner.snapshot:
            report += f"\ncurrent.json now names {now}: main moved during the run, and the run kept the pinned snapshot"
    calls = getattr(inner, "calls", [])
    if calls:
        report += (f"\n\nTokens: {sum(c.input_tokens for c in calls)} in, {sum(c.output_tokens for c in calls)} out, "
                   f"over {len(calls)} calls; tool calls: {sum(len(c.tools) for c in calls)}")
    print(report)
    if args.out:
        args.out.write_text(json.dumps({"agent": args.agent, "split": args.split, "replies": replies,
                                        "calls": [vars(c) for c in calls], "not_run": not_run}, indent=2) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
