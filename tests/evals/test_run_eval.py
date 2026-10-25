"""The Tier 2 runner, checked with stand-in agents on the 66 validation tickets. Every check here must be able to fail."""

import copy

import pytest

from evals.run_eval import (FIRST_PASS_REASON, TicketResult, Verdict, first_pass_review, format_report,
                             load_requests, main, review_for, run, summarise)
from evals.stand_in_agents import always_stop, perfect

REQUESTS = load_requests("validation")
KEYS = {r.number: r.expected for r in REQUESTS}


def perfect_except(number, change):
    """Build the perfect agent, but let `change` rewrite its reply for one ticket."""
    base = perfect(KEYS)

    def agent(ticket, engineer_review=None, dns_lookup=None):
        """Answer like the perfect agent, changed on one ticket."""
        reply = base(ticket)
        return change(reply) if ticket["number"] == number else reply

    return agent


def result_for(results, number):
    """Pick one ticket's result out of a run."""
    return next(r for r in results if r.number == number)


def test_the_perfect_agent_passes_every_ticket_complete():
    """66 of 66 passed and complete, no incomplete and no mistakes, so the runner adds nothing of its own."""
    s = summarise(run(perfect(KEYS)))
    assert (s["tickets"], s["passed"], s["complete"], s["incomplete"]) == (66, 66, 66, 0)
    assert all(count == 0 for count in s["mistakes"].values())


def test_the_always_stop_agent_gives_the_known_baseline():
    """Always-stop passes 3 stops, gives the wrong reason on 23, and over-abstains on all 40 non-stops."""
    s = summarise(run(always_stop))
    assert (s["passed"], s["stops"]) == (3, 26)
    assert s["mistakes"]["wrong_reason"] == 23
    assert s["mistakes"]["over_abstain"] == 40
    assert s["mistakes"]["wrong_outcome"] == 40
    assert s["mistakes"]["missed_stop"] == 0


def test_the_agent_sees_a_copy_of_the_ticket_and_never_the_answer_key():
    """A spy agent gets only ticket fields, and its edits to them do not reach the labels."""
    before = copy.deepcopy(KEYS)
    seen, reviews, lookups = [], [], {}

    def spy(ticket, engineer_review=None, dns_lookup=None):
        """Record what arrives, then vandalise it."""
        seen.append(set(ticket))
        reviews.append(copy.deepcopy(engineer_review))
        if dns_lookup is not None:
            lookups[ticket["number"]] = dns_lookup
        ticket.clear()
        if engineer_review is not None:
            engineer_review.clear()
        return {"outcome": "stop_and_ask", "reason": "free_text_conflict", "rules": []}

    # Check outside the agent: the runner turns anything raised inside it into agent_error.
    results = run(spy)
    assert len(seen) == 66
    assert seen == [set(r.ticket) for r in REQUESTS]
    # The engineer's decision when the request has one, else the acceptance of a ticket with no findings.
    assert reviews == [review_for(r) for r in REQUESTS]
    assert any(reviews), "no request carries an engineer_review block, so this check proves nothing"
    assert {r.number: r.engineer_review for r in load_requests("validation")} == \
        {r.number: r.engineer_review for r in REQUESTS}  # vandalising the copy did not reach the file
    assert not any("agent_error" in r.verdict.mistakes for r in results)
    assert set(lookups) == {r.number for r in REQUESTS if r.dns} == {"RITM0011069"}
    assert all(callable(f) and not isinstance(f, dict) for f in lookups.values())  # a resolver, never the dns: block
    assert {r.number: r.expected for r in load_requests("validation")} == before
    assert {r.number: r.expected for r in REQUESTS} == before


def test_a_missing_site_rule_passes_but_is_reported_incomplete():
    """Dropping the DR site's rule on RITM0011001 allows less: passed, not complete, and counted apart."""
    def drop_dr(reply):
        """Remove the last rule."""
        reply["rules"].pop()
        return reply

    results = run(perfect_except("RITM0011001", drop_dr))
    r = result_for(results, "RITM0011001")
    assert r.verdict.passed and not r.verdict.complete
    assert r.verdict.incomplete == ["prod-centralus/ledg/allow-ledg-network-rules: rule missing"]
    s = summarise(results)
    assert (s["passed"], s["complete"], s["incomplete"]) == (66, 65, 1)


def test_a_wider_port_fails_as_too_wide():
    """Port 22 widened to 22-23 on RITM0011001 is excess access, so the ticket fails."""
    def widen(reply):
        """Open one extra port on the first rule."""
        reply["rules"][0]["ports"] = ["22-23"]
        return reply

    r = result_for(run(perfect_except("RITM0011001", widen)), "RITM0011001")
    assert not r.verdict.passed
    assert r.verdict.mistakes == ["too_wide"]


@pytest.mark.parametrize("number, env_site, source, mistake", [
    ("RITM0011041", "stage-centralus", "10.103.15.0/24", "too_wide"),  # add, primary only
    ("RITM0011045", "lab-centralus", "10.107.14.0/24", "wrong_removal"),  # removal, primary only
])
def test_a_rule_at_an_unselected_site_fails(number, env_site, source, mistake):
    """A primary-only ticket answered with a DR copy as well changes a site nobody asked for."""
    def add_dr(reply):
        """Copy the first rule to the DR site."""
        reply["rules"].append({**reply["rules"][0], "env_site": env_site, "sources": [source]})
        return reply

    r = result_for(run(perfect_except(number, add_dr)), number)
    assert r.verdict.mistakes == [mistake]


def test_drafting_an_already_allowed_ticket_fails_as_wrong_outcome():
    """RITM0011025 is already allowed; answering draft is the wrong outcome word."""
    def draft(reply):
        """Swap the outcome to draft."""
        reply["outcome"] = "draft"
        return reply

    r = result_for(run(perfect_except("RITM0011025", draft)), "RITM0011025")
    assert "wrong_outcome" in r.verdict.mistakes
    assert r.reply_outcome == "draft" and r.expected_outcome == "already_allowed"


def test_a_crash_fails_one_ticket_and_the_run_goes_on():
    """An exception on one ticket is agent_error there; the other 65 are still scored."""
    def crash(reply):
        """Fail the way a broken agent would."""
        raise RuntimeError("model timed out")

    results = run(perfect_except("RITM0011010", crash))
    assert len(results) == 66
    r = result_for(results, "RITM0011010")
    assert r.verdict.mistakes == ["agent_error"] and r.reply_outcome == "?"
    assert "RuntimeError: model timed out" in r.verdict.detail
    assert summarise(results)["complete"] == 65


def test_the_test_split_is_sealed(capsys):
    """Reading the test split without allow_test is refused, in code and on the command line."""
    with pytest.raises(PermissionError):
        load_requests("test")
    with pytest.raises(PermissionError):
        run(always_stop, "test")
    assert main(["--agent", "always_stop", "--split", "test"]) == 2
    assert capsys.readouterr().out.startswith("refused:")


@pytest.mark.parametrize("agent", [perfect(KEYS), always_stop], ids=["perfect", "always_stop"])
def test_category_rows_add_up_to_the_totals(agent):
    """The by-category table counts every ticket once and matches the headline."""
    s = summarise(run(agent))
    rows = s["by_category"].values()
    assert sum(total for _, total in rows) == s["tickets"] == 66
    assert sum(done for done, _ in rows) == s["complete"]


def test_unreviewed_answer_keys_are_flagged_on_the_score_sheet():
    """Every label marked `review: pending` is counted, and the sheet says so on the headline and per ticket."""
    results = run(perfect(KEYS))
    pending = {r.number for r in REQUESTS if r.expected.get("review") == "pending"}
    assert {r.number for r in results if r.label_pending} == pending
    assert summarise(results)["labels_pending"] == len(pending)
    one = [TicketResult("RITM0000001", "c", "draft", "draft", Verdict(), label_pending=True),
           TicketResult("RITM0000002", "c", "draft", "draft", Verdict())]
    report = format_report(one, "validation", "x")
    assert "Labels pending human review         1 / 2" in report
    assert report.count("label pending review") == 1
    assert "pending" not in format_report(one[1:], "validation", "x")


def test_first_pass_and_after_review_tickets_are_counted_apart():
    """Two validation tickets resume with the engineer's acceptance; the sheet reports them on their own line."""
    results = run(perfect(KEYS))
    resumed = {r.number for r in REQUESTS if r.engineer_review is not None}
    assert {r.number for r in results if r.after_review} == resumed and len(resumed) == 2
    s = summarise(results)
    assert s["after_review"] == (2, 2)
    report = format_report(results, "validation", "perfect")
    assert "First pass, passed and complete    64 / 64" in report
    assert "After engineer review, passed       2 / 2" in report


def test_every_ticket_reaches_the_agent_with_an_acceptance_of_its_exact_version():
    """No ticket is sent with engineer_review null: first-pass tickets get an acceptance with nothing accepted."""
    reviews = {}

    def spy(ticket, engineer_review=None, dns_lookup=None):
        """Record the acceptance each ticket arrives with."""
        reviews[ticket["number"]] = engineer_review
        return {"outcome": "stop_and_ask", "reason": "free_text_conflict", "rules": []}

    run(spy)
    from workflow.intake import ticket_version
    assert len(reviews) == 66 and None not in reviews.values()
    first_pass = [r for r in REQUESTS if r.engineer_review is None]
    assert len(first_pass) == 64
    for r in first_pass:
        review = reviews[r.number]
        assert review["decision"] == "accept" and review["ticket_version"] == ticket_version(r.ticket), r.number
        assert review["engineer"] == r.ticket["assigned_to"] and review["reason"] == FIRST_PASS_REASON
        assert review["accepted"] == review["planned"] == review["edits"] == [], r.number


def test_a_first_pass_acceptance_is_exactly_what_accept_sends_the_agent(tmp_path, monkeypatch):
    """Submit and accept a no-findings ticket through the workflow; the agent's review equals the runner's."""
    import yaml
    import workflow.cli as cli
    request = next(r for r in REQUESTS if r.engineer_review is None and not r.dns)
    path = tmp_path / f"{request.number}.yaml"
    path.write_text(yaml.safe_dump(request.ticket, sort_keys=False))
    monkeypatch.setenv("FWAGENT_STATE_DIR", str(tmp_path / "state"))
    sent = []

    def capture(repo, ticket, review, reply_path):
        """Keep what the agent would receive, then stop before any file is drafted."""
        sent.append(copy.deepcopy(review))
        raise cli.Refused("captured")

    monkeypatch.setattr(cli, "agent_reply", capture)
    cli.submit(cli.REPO, str(path))
    version = cli.load_record(cli.REPO, request.number)["ticket_version"]
    with pytest.raises(cli.Refused, match="captured"):
        cli.accept(cli.REPO, request.number, version[:12], request.ticket["assigned_to"], FIRST_PASS_REASON, None, None)
    assert sent == [first_pass_review(request.ticket)]


@pytest.mark.parametrize("number", [r.number for r in REQUESTS if r.engineer_review is not None])
def test_an_after_review_acceptance_is_what_production_sends_after_the_agent_stops(number, tmp_path, monkeypatch):
    """Walk the workflow: submit, accept, the agent stops on the accepted code, accept again; the second review matches."""
    import yaml
    import workflow.cli as cli
    request = next(r for r in REQUESTS if r.number == number)
    recorded = request.engineer_review
    path = tmp_path / f"{number}.yaml"
    path.write_text(yaml.safe_dump(request.ticket, sort_keys=False))
    planned = tmp_path / "planned.yaml"
    planned.write_text(yaml.safe_dump(recorded["planned"]))
    monkeypatch.setenv("FWAGENT_STATE_DIR", str(tmp_path / "state"))
    sent = []

    def agent(repo, ticket, review, reply_path):
        """First call: stop on the code the engineer later accepts. Second call: keep the review and stop the test."""
        sent.append(copy.deepcopy(review))
        if len(sent) == 1:
            return {"outcome": "stop_and_ask", "reason": recorded["accepted"][0], "rules": [],
                    "explanation": "stand-in stop"}, "replay"
        raise cli.Refused("captured")

    monkeypatch.setattr(cli, "agent_reply", agent)
    cli.submit(cli.REPO, str(path))
    version = cli.load_record(cli.REPO, number)["ticket_version"]
    assert cli.load_record(cli.REPO, number)["findings"] == []  # submit finds nothing; the agent raises the finding
    cli.accept(cli.REPO, number, version[:12], recorded["engineer"], FIRST_PASS_REASON, None, None)
    assert cli.load_record(cli.REPO, number)["status"] == "awaiting_review"
    with pytest.raises(cli.Refused, match="captured"):
        cli.accept(cli.REPO, number, version[:12], recorded["engineer"], recorded["reason"],
                   str(planned) if recorded["planned"] else None, None)
    assert sent[1] == review_for(request)


def test_an_acceptance_for_another_ticket_version_is_refused(tmp_path, monkeypatch):
    """Edit one value in an accepted ticket: its engineer_review no longer covers it, so loading fails."""
    import shutil
    import evals.run_eval as runner
    shutil.copytree(runner.REQUESTS / "validation", tmp_path / "validation")
    path = next(p for p in (tmp_path / "validation").glob("*.yaml") if "engineer_review:" in p.read_text())
    path.write_text(path.read_text().replace("ports: ['", "ports: ['1", 1))
    monkeypatch.setattr(runner, "REQUESTS", tmp_path)
    with pytest.raises(ValueError, match="another ticket version"):
        load_requests("validation")


@pytest.mark.parametrize("old, new, why", [("exchange.northwind.example: timeout", "other.northwind.example: timeout",
                                             "it must be a ticket hostname"),
                                            ("exchange.northwind.example: timeout", "exchange.northwind.example: slow",
                                             "one of")], ids=["host not on the ticket", "unknown fault"])
def test_a_dns_condition_must_name_a_ticket_host_and_a_known_fault(tmp_path, monkeypatch, old, new, why):
    """A dns: block can only shape the lookup of a name the ticket gives, so it cannot smuggle in other answers."""
    import shutil
    import evals.run_eval as runner
    shutil.copytree(runner.REQUESTS / "validation", tmp_path / "validation")
    path = tmp_path / "validation" / "validation_RITM0011069.yaml"
    assert old in path.read_text()
    path.write_text(path.read_text().replace(old, new))
    monkeypatch.setattr(runner, "REQUESTS", tmp_path)
    with pytest.raises(ValueError, match=why):
        load_requests("validation")


def test_reviewed_only_leaves_out_every_pending_label_and_says_so(tmp_path, monkeypatch):
    """Mark two labels pending in a copy (every real label is reviewed); only those two are left out."""
    import shutil
    import evals.run_eval as runner
    shutil.copytree(runner.REQUESTS / "validation", tmp_path / "validation")
    marked = sorted((tmp_path / "validation").glob("*.yaml"))[:2]
    for path in marked:
        path.write_text(path.read_text().replace("\nexpected:\n", "\nexpected:\n  review: pending\n", 1))
    monkeypatch.setattr(runner, "REQUESTS", tmp_path)
    requests = load_requests("validation")
    pending = {r.number for r in requests if r.expected.get("review") == "pending"}
    assert len(pending) == 2
    not_run = []
    results = run(perfect({r.number: r.expected for r in requests}), reviewed_only=True, not_run=not_run)
    assert {n for n, _ in not_run} == pending and all(why == "label pending review" for _, why in not_run)
    assert len(results) == len(requests) - 2 and not any(r.label_pending for r in results)


def test_an_agent_whose_dns_tool_runs_in_azure_does_not_get_a_controlled_dns_request():
    base = perfect(KEYS)

    def hosted(ticket, engineer_review=None, dns_lookup=None):
        """Like the hosted drafter: a controlled DNS answer would never reach its tool."""
        assert dns_lookup is None
        return base(ticket)

    hosted.controlled_dns = False
    not_run = []
    results = run(hosted, not_run=not_run)
    assert not_run == [("RITM0011069", "needs a controlled DNS answer the deployed tool cannot get")]
    assert len(results) == len(REQUESTS) - 1 and not any("agent_error" in r.verdict.mistakes for r in results)


def test_the_token_budget_stops_the_run_before_the_next_ticket_and_lists_the_rest():
    from workflow.agent import Call
    base = perfect(KEYS)

    class Metered:
        """A stand-in that records 1,000 tokens per call."""
        calls = []

        def __call__(self, ticket, **extra):
            self.calls.append(Call(ticket["number"], 900, 100))
            return base(ticket)

    metered, not_run = Metered(), []
    results = run(metered, token_budget=3000, not_run=not_run)
    assert len(results) == 3 and len(not_run) == len(REQUESTS) - 3
    assert {why for _, why in not_run} == {"token budget reached"}


def test_replies_are_kept_for_the_record():
    replies = []
    run(always_stop, replies=replies)
    assert len(replies) == len(REQUESTS) and replies[0]["reply"]["outcome"] == "stop_and_ask"


def test_a_ticket_left_out_by_the_caller_is_listed_with_its_reason():
    not_run = []
    results = run(perfect(KEYS), not_run=not_run, skip={"RITM0011068": "snapshot lacks its rule"})
    assert not_run == [("RITM0011068", "snapshot lacks its rule")] and "RITM0011068" not in {r.number for r in results}


def test_the_foundry_run_refuses_data_that_differs_from_the_snapshot_unless_each_file_is_named(monkeypatch, capsys):
    import workflow.agent as agent_mod

    def from_env(cls, repo, allowed_differences=(), container=None):
        """Like the real one: refuse unless the one differing file is named."""
        if "infra/envs/x.tfvars" not in allowed_differences:
            raise agent_mod.AgentError("this checkout's data differs from snapshot cccc: infra/envs/x.tfvars")
        return always_stop

    monkeypatch.setattr(agent_mod.FoundryAgent, "from_env", classmethod(from_env))
    assert main(["--agent", "foundry"]) == 2 and "infra/envs/x.tfvars" in capsys.readouterr().out
    assert main(["--agent", "foundry", "--data-diff-ok", "infra/envs/x.tfvars", "--only", "RITM0011001"]) == 0


def test_tickets_left_out_by_only_are_listed_as_not_run_and_never_written_as_replies(tmp_path, capsys):
    import json

    out = tmp_path / "run.json"
    assert main(["--agent", "perfect", "--only", "RITM0011002", "--out", str(out)]) == 0
    record = json.loads(out.read_text())
    assert [r["number"] for r in record["replies"]] == ["RITM0011002"]
    assert record["replies"][0]["mistakes"] == []
    others = {r.number for r in REQUESTS} - {"RITM0011002"}
    assert {n for n, _ in record["not_run"]} == others
    assert {why for _, why in record["not_run"]} == {"not selected with --only"}
    sheet = capsys.readouterr().out
    assert "validation split · 1 tickets" in sheet and "RITM0011003  not selected with --only" in sheet


# ------------------------------------------------- throttling, pacing and infrastructure errors

class Clock:
    """A fake clock: sleep moves it forward and records each wait."""

    def __init__(self):
        self.now, self.waits = 0.0, []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        """Record the wait and move time forward by it."""
        self.waits.append(seconds)
        self.now += seconds


def scripted(failures, tokens=0, clock=None, interrupt_at=None):
    """The perfect stand-in, but raising failures[number] (a list, one per attempt) before it answers.

    Each answered call records `tokens`, as a Foundry call does; with a clock, each call also takes 5 seconds.
    """
    from workflow.agent import Call
    base, left = perfect(KEYS), {n: list(errors) for n, errors in failures.items()}

    class Scripted:
        """Answers like the perfect agent after its scripted failures."""
        calls = []

        def __call__(self, ticket, **extra):
            """Raise the next scripted failure for this ticket, or answer."""
            if ticket["number"] == interrupt_at:
                raise KeyboardInterrupt
            if clock is not None:
                clock.now += 5
            self.calls.append(Call(ticket["number"]))
            if left.get(ticket["number"]):
                self.calls[-1].error = "scripted"
                raise left[ticket["number"]].pop(0)
            self.calls[-1].input_tokens = tokens
            return base(ticket)

    return Scripted()


def throttled(wait=None):
    """The error the agent raises when the deployment throttles a call."""
    from workflow.agent import RateLimited
    return RateLimited("the agent call failed: InternalServerError: rate_limit_exceeded", retry_after=wait)


def test_a_throttled_ticket_is_retried_after_the_wait_and_every_attempt_is_recorded():
    clock, attempts = Clock(), []
    agent = scripted({"RITM0011002": [throttled(12.0), throttled()]})
    results = run(agent, attempts=attempts, max_attempts=3, sleep=clock.sleep, clock=clock, jitter=lambda: 1.0)
    assert result_for(results, "RITM0011002").verdict.complete
    mine = [a for a in attempts if a["number"] == "RITM0011002"]
    assert [(a["attempt"], a["kind"]) for a in mine] == [(1, "rate_limit"), (2, "rate_limit"), (3, None)]
    assert clock.waits == [13.0, 61.0]  # the server's wait, else a full minute, each plus jitter
    assert [a["waited"] for a in mine] == [13.0, 61.0, 0]


def test_a_ticket_throttled_on_every_attempt_is_not_run_and_never_scored():
    clock, attempts, not_run = Clock(), [], []
    agent = scripted({"RITM0011002": [throttled(), throttled(), throttled()]})
    results = run(agent, attempts=attempts, not_run=not_run, max_attempts=3, sleep=clock.sleep, clock=clock,
                  jitter=lambda: 0.0)
    assert "RITM0011002" not in {r.number for r in results} and len(results) == len(REQUESTS) - 1
    assert not_run == [("RITM0011002", "infrastructure: rate_limit_exceeded on all 3 attempts")]
    assert [a["kind"] for a in attempts if a["number"] == "RITM0011002"] == ["rate_limit"] * 3
    assert clock.waits == [60.0, 60.0]  # no wait after the last attempt


def test_a_response_returned_as_failed_by_the_rate_limit_is_retried_and_never_written_as_a_reply():
    # RITM0011003 on 2026-10-24: the outer trace span said OK while the agent itself hit the rate limit
    from types import SimpleNamespace
    from workflow.agent import FoundryAgent
    reply = '{"outcome": "draft", "rules": []}'
    failed = SimpleNamespace(status="failed", error=SimpleNamespace(code="rate_limit_exceeded", message="throttled"),
                             output_text=reply, output=[], usage=SimpleNamespace(input_tokens=0, output_tokens=0))
    openai = SimpleNamespace(responses=SimpleNamespace(create=lambda **kwargs: failed))
    agent = FoundryAgent(SimpleNamespace(), openai, "2", "c" * 40)
    clock, attempts, not_run, replies = Clock(), [], [], []
    results = run(agent, only={"RITM0011003"}, attempts=attempts, not_run=not_run, replies=replies, max_attempts=3,
                  sleep=clock.sleep, clock=clock, jitter=lambda: 0.0)
    assert results == [] and replies == []
    assert [a["kind"] for a in attempts] == ["rate_limit"] * 3
    assert ("RITM0011003", "infrastructure: rate_limit_exceeded on all 3 attempts") in not_run


def test_other_infrastructure_errors_are_not_retried_and_never_scored():
    from workflow.agent import InfraError
    attempts, not_run = [], []
    agent = scripted({"RITM0011002": [InfraError("the agent call failed: AuthenticationError: 401")]})
    results = run(agent, attempts=attempts, not_run=not_run, max_attempts=3, sleep=Clock().sleep)
    assert not_run == [("RITM0011002", "infrastructure: the agent call failed: AuthenticationError: 401")]
    assert [a["kind"] for a in attempts if a["number"] == "RITM0011002"] == ["infrastructure"]
    assert not any("agent_error" in r.verdict.mistakes for r in results)


def test_a_model_error_is_not_retried_and_still_fails_its_ticket():
    from workflow.agent import AgentError
    attempts = []
    agent = scripted({"RITM0011033": [AgentError("the agent's reply does not fit agents/reply.schema.json")]})
    results = run(agent, attempts=attempts, max_attempts=3, sleep=Clock().sleep)
    assert result_for(results, "RITM0011033").verdict.mistakes == ["agent_error"]
    assert [a["kind"] for a in attempts if a["number"] == "RITM0011033"] == ["model"]


def test_tickets_wait_until_the_last_minute_has_room_for_another_ticket():
    clock = Clock()
    agent = scripted({}, tokens=10_000, clock=clock)
    run(agent, sleep=clock.sleep, clock=clock, pace_tokens=15_000, max_attempts=3)
    # each ticket uses 10,000; a second inside the same minute would make 20,000 > 15,000
    assert clock.waits[:2] == [55.0, 55.0] and len(clock.waits) == len(REQUESTS) - 1


def test_three_tickets_in_a_row_failing_on_infrastructure_stop_the_run():
    first = [r.number for r in REQUESTS[:3]]
    clock, not_run = Clock(), []
    agent = scripted({n: [throttled()] * 3 for n in first})
    results = run(agent, not_run=not_run, max_attempts=3, sleep=clock.sleep, clock=clock, jitter=lambda: 0.0)
    assert results == [] and [n for n, _ in not_run[:3]] == first
    rest = not_run[3:]
    assert len(rest) == len(REQUESTS) - 3
    assert {why for _, why in rest} == {"run stopped: 3 tickets in a row failed on infrastructure"}


def test_an_interrupt_keeps_what_finished_and_lists_the_rest_as_not_run():
    third = REQUESTS[2].number
    not_run, replies = [], []
    try:
        results = run(scripted({}, interrupt_at=third), not_run=not_run, replies=replies)
    except KeyboardInterrupt:
        pytest.fail("the interrupt escaped the run instead of stopping it gracefully")
    assert [r.number for r in results] == [r.number for r in REQUESTS[:2]] and len(replies) == 2
    assert not_run[0] == (third, "run interrupted") and len(not_run) == len(REQUESTS) - 2


def test_pacing_counts_each_model_call_not_only_billed_tokens():
    from workflow.agent import Call
    clock, base = Clock(), perfect(KEYS)

    class TwoTools:
        """Bills only 1,000 tokens a ticket, but makes three model calls: before, between and after two tools."""
        calls = []

        def __call__(self, ticket, **extra):
            """Answer, recording two tool calls and 1,000 billed tokens."""
            clock.now += 5
            self.calls.append(Call(ticket["number"], input_tokens=1000, tools=["locate", "duplicate"]))
            return base(ticket)

    run(TwoTools(), sleep=clock.sleep, clock=clock, pace_tokens=30_000, reserve_per_call=8_000)
    assert clock.waits[:2] == [55.0, 55.0]  # 3 x 8,000 = 24,000 a ticket; two would be 48,000 > 30,000


def test_progress_is_reported_after_every_ticket_with_the_count_so_far():
    seen = []
    run(scripted({"RITM0011002": [throttled()] * 3}), max_attempts=3, sleep=Clock().sleep, jitter=lambda: 0.0,
        progress=seen.append)
    assert [e["number"] for e in seen] == [r.number for r in REQUESTS]
    second = seen[1]
    assert (second["status"], second["attempts"], second["done"], second["total"]) == ("not_run", 3, 2, len(REQUESTS))
    assert second["why"] == "infrastructure: rate_limit_exceeded on all 3 attempts" and seen[0]["status"] == "scored"


def _interrupting(monkeypatch, how):
    """Make --agent perfect stop on the third ticket, by KeyboardInterrupt or by SIGTERM to this process."""
    import os
    import signal
    import evals.run_eval as run_eval
    third = REQUESTS[2].number
    base = perfect(KEYS)

    def agent(ticket, **extra):
        """Answer, but stop the run at the third ticket."""
        if ticket["number"] == third:
            if how == "sigterm":
                os.kill(os.getpid(), signal.SIGTERM)
            raise KeyboardInterrupt
        return base(ticket)

    monkeypatch.setattr(run_eval, "perfect", lambda keys: agent)
    return third


@pytest.mark.parametrize("how", ["interrupt", "sigterm"])
def test_a_stopped_run_still_writes_what_finished_and_says_it_stopped(tmp_path, capsys, monkeypatch, how):
    import json
    import signal
    before = signal.getsignal(signal.SIGTERM)
    third = _interrupting(monkeypatch, how)
    out = tmp_path / "run.json"
    try:
        code = main(["--agent", "perfect", "--out", str(out)])
    except KeyboardInterrupt:
        pytest.fail("the interrupt escaped main instead of stopping the run gracefully")
    assert code == 130
    record = json.loads(out.read_text())
    assert record["status"] == "interrupted" and len(record["replies"]) == 2
    assert record["not_run"][0] == [third, "run interrupted"] and len(record["not_run"]) == len(REQUESTS) - 2
    captured = capsys.readouterr()
    assert "run interrupted" in captured.out and f"[2/{len(REQUESTS)}]" in captured.err
    assert signal.getsignal(signal.SIGTERM) == before  # the handler is put back


def test_the_out_file_is_rewritten_after_every_ticket(tmp_path, monkeypatch):
    import json
    import evals.run_eval as run_eval
    out, sizes = tmp_path / "run.json", []
    real = run_eval._save

    def save(path, record):
        """Save as usual, then note how many replies the file holds."""
        real(path, record)
        sizes.append(len(json.loads(path.read_text())["replies"]))

    monkeypatch.setattr(run_eval, "_save", save)
    assert main(["--agent", "perfect", "--only", "RITM0011001", "RITM0011002", "--out", str(out)]) == 0
    # saved after each attempt (the reply is not in yet) and again after each ticket
    assert sizes[:5] == [0, 1, 1, 2, 2] and json.loads(out.read_text())["status"] == "complete"


def test_coverage_separates_answered_tickets_from_throttled_and_other_not_run():
    from evals.run_eval import coverage
    results = run(perfect(KEYS))[:3]
    not_run = [("A", "infrastructure: rate_limit_exceeded on all 3 attempts"),
               ("B", "infrastructure: the agent call failed: AuthenticationError: 401"),
               ("C", "run stopped: 3 tickets in a row failed on infrastructure"),
               ("D", "needs a controlled DNS answer the deployed tool cannot get"), ("E", "not selected with --only")]
    text = coverage(results, not_run)
    assert "Answered and scored                 3 / 8" in text
    assert "Throttled (rate limit)              1 / 8" in text
    assert "Other infrastructure error          1 / 8" in text
    assert "Run stopped or interrupted          1 / 8" in text
    assert "Left out by design or selection     2 / 8" in text


def test_the_sheet_leads_with_completion_so_failed_calls_cannot_hide_behind_the_pass_rate():
    """3 answered and passed, 2 failed calls, 1 left out: the headline says 3 of 5 attempted, not 3 of 3."""
    results = run(perfect(KEYS))[:3]
    not_run = [("A", "infrastructure: rate_limit_exceeded on all 3 attempts"),
               ("B", "infrastructure: the agent call failed: AuthenticationError: 401"),
               ("E", "not selected with --only")]
    report = format_report(results, "validation", "x", not_run)
    head = report.split("Passed and complete               ")[0]
    assert "Answered and scored                 3 / 5 attempted   (2 failed service calls: 1 throttled, 1 other)" in head
    assert "Not attempted                       1" in head
    assert "Passed and complete, of attempted   3 / 5   (a failed service call is never a pass)" in head
    assert "Passed and complete                 3 / 3" in report  # the rate on answered tickets stays, below it


WRITE_WATCH = """
import hashlib, os, sys
from pathlib import Path
writes = []
def hook(event, args):
    if event == "open" and args[1] is not None and any(c in str(args[1]) for c in "wax+"):
        writes.append(("open", str(args[0])))
    elif event == "os.open" and args[2] & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND):
        writes.append(("os.open", str(args[0])))
    elif event in ("os.mkdir", "os.rename", "os.replace", "os.remove", "os.rmdir", "os.truncate", "shutil.copyfile"):
        writes.append((event, str(args[0])))
def tree():
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest()
            for root in ("infra/envs", "data/network") for p in sorted(Path(root).rglob("*")) if p.is_file()}
before = tree()
sys.addaudithook(hook)
import evals.run_eval as runner
print("IMPORT", writes)
if sys.argv[1] == "run":
    from evals.stand_in_agents import always_stop, perfect
    keys = {r.number: r.expected for r in runner.load_requests("validation")}
    for agent in (perfect(keys), always_stop):
        assert len(runner.run(agent)) == 66
print("ALL", writes)
print("SAME", tree() == before and len(before) > 0)
"""


@pytest.mark.parametrize("mode", ["import", "run"])
def test_importing_the_runner_and_running_it_writes_no_file(mode, tmp_path):
    """Watch every file write while the runner is imported, then run over all 66 tickets: none, and no tfvars change."""
    import os
    import subprocess
    import sys
    from evals.run_eval import REQUESTS
    repo = REQUESTS.parents[1]
    env = {k: v for k, v in os.environ.items() if not k.startswith("FWAGENT_")}
    env.update(PYTHONDONTWRITEBYTECODE="1", HOME=str(tmp_path))  # no .pyc files; a default state folder would land here
    out = subprocess.run([sys.executable, "-c", WRITE_WATCH, mode], cwd=repo, env=env, capture_output=True, text=True,
                         timeout=300)
    assert out.returncode == 0, out.stderr
    assert "IMPORT []" in out.stdout and "ALL []" in out.stdout and "SAME True" in out.stdout, out.stdout
    assert not any(tmp_path.iterdir())  # no state folder, nothing under the home folder


def test_the_foundry_run_refuses_an_agent_version_other_than_the_one_required(monkeypatch, capsys):
    import workflow.agent as agent_mod

    class Pinned:
        """A published agent at version 3."""
        version, snapshot, calls, controlled_dns = "3", "c" * 40, [], False

        def __call__(self, ticket, **extra):
            """Never called: the run refuses first."""
            raise AssertionError("called")

        def pointer_now(self):
            """The pointer has not moved."""
            return self.snapshot

    monkeypatch.setattr(agent_mod.FoundryAgent, "from_env", classmethod(lambda cls, repo, allowed_differences=(): Pinned()))
    assert main(["--agent", "foundry", "--agent-version", "2"]) == 2
    assert "agent version 3, but this run requires version 2" in capsys.readouterr().out


def test_attempts_start_at_least_the_minimum_gap_apart_including_retries():
    clock, attempts = Clock(), []
    agent = scripted({REQUESTS[1].number: [throttled(5.0)]}, clock=clock)
    run(agent, attempts=attempts, sleep=clock.sleep, clock=clock, min_gap=60, max_attempts=3, jitter=lambda: 0.0)
    starts = [a["at"] for a in attempts]
    assert all(b - a >= 60 for a, b in zip(starts, starts[1:]))
    assert clock.waits[:3] == [55.0, 5.0, 50.0]  # gap after ticket 1; Azure's 5 s; then the rest of the gap


def test_every_attempt_is_saved_to_disk_as_soon_as_it_ends(tmp_path, monkeypatch):
    import json
    from types import SimpleNamespace
    import evals.run_eval as run_eval
    clock = Clock()
    agent = scripted({"RITM0011001": [throttled(), throttled()]}, clock=clock)
    monkeypatch.setattr(run_eval, "perfect", lambda keys: agent)
    monkeypatch.setattr(run_eval, "time", SimpleNamespace(sleep=clock.sleep, monotonic=clock))
    out, saved = tmp_path / "run.json", []
    real = run_eval._save

    def save(path, record):
        """Save as usual, then note how many attempts the file on disk holds."""
        real(path, record)
        saved.append(len(json.loads(path.read_text())["attempts"]))

    monkeypatch.setattr(run_eval, "_save", save)
    assert main(["--agent", "perfect", "--only", "RITM0011001", "--out", str(out)]) == 0
    assert saved[:3] == [1, 2, 3]  # each throttled attempt is on disk before the wait for the next
    record = json.loads(out.read_text())
    assert [a["kind"] for a in record["attempts"]] == ["rate_limit", "rate_limit", None]
    assert clock.waits and min(clock.waits) >= 60  # the waits went to the fake clock, each at least a minute


def test_a_longer_azure_retry_delay_always_wins_over_the_minimum_gap():
    clock, attempts = Clock(), []
    agent = scripted({REQUESTS[0].number: [throttled(120.0)]}, clock=clock)
    run(agent, attempts=attempts, sleep=clock.sleep, clock=clock, min_gap=60, max_attempts=3, jitter=lambda: 0.0)
    first, second = attempts[0], attempts[1]
    assert clock.waits[0] == 120.0 and first["waited"] == 120.0
    assert second["at"] - (first["at"] + 5) >= 120  # 120 s after the throttled attempt ended, with no gap shortening it


def test_stop_on_failure_stops_after_the_first_answer_that_does_not_pass():
    second = REQUESTS[1].number
    agent = perfect_except(second, lambda reply: {**reply, "outcome": "already_allowed"})
    not_run = []
    results = run(agent, not_run=not_run, stop_on_failure=True)
    assert [r.number for r in results] == [REQUESTS[0].number, second] and not result_for(results, second).verdict.passed
    assert {why for _, why in not_run} == {f"run stopped: {second} did not pass"} and len(not_run) == len(REQUESTS) - 2


def test_stop_on_failure_stops_after_the_first_infrastructure_failure():
    from workflow.agent import InfraError
    first = REQUESTS[0].number
    not_run = []
    results = run(scripted({first: [InfraError("the agent call failed: AuthenticationError: 401")]}), not_run=not_run,
                  stop_on_failure=True, sleep=Clock().sleep)
    assert results == [] and not_run[0] == (first, "infrastructure: the agent call failed: AuthenticationError: 401")
    assert {why for _, why in not_run[1:]} == {f"run stopped: {first} failed on infrastructure"}


def test_stop_on_failure_counts_a_ticket_that_runs_out_of_throttle_retries():
    first = REQUESTS[0].number
    not_run = []
    run(scripted({first: [throttled()] * 2}), not_run=not_run, stop_on_failure=True, max_attempts=2,
        sleep=Clock().sleep, jitter=lambda: 0.0)
    assert not_run[0] == (first, "infrastructure: rate_limit_exceeded on all 2 attempts")
    assert {why for _, why in not_run[1:]} == {f"run stopped: {first} failed on infrastructure"}


def test_stop_on_failure_does_not_stop_a_passing_run():
    not_run = []
    results = run(perfect(KEYS), not_run=not_run, stop_on_failure=True)
    assert len(results) == len(REQUESTS) and not_run == []
