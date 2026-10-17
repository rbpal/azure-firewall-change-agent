"""The Tier 2 runner, checked with stand-in agents on the 40 validation tickets. Every check here must be able to fail."""

import copy

import pytest

from evals.run_eval import load_requests, main, run, summarise
from evals.stand_in_agents import always_stop, perfect

REQUESTS = load_requests("validation")
KEYS = {r.number: r.expected for r in REQUESTS}


def perfect_except(number, change):
    """Build the perfect agent, but let `change` rewrite its reply for one ticket."""
    base = perfect(KEYS)

    def agent(ticket):
        """Answer like the perfect agent, changed on one ticket."""
        reply = base(ticket)
        return change(reply) if ticket["number"] == number else reply

    return agent


def result_for(results, number):
    """Pick one ticket's result out of a run."""
    return next(r for r in results if r.number == number)


def test_the_perfect_agent_passes_every_ticket_complete():
    """40 of 40 passed and complete, no incomplete and no mistakes, so the runner adds nothing of its own."""
    s = summarise(run(perfect(KEYS)))
    assert (s["tickets"], s["passed"], s["complete"], s["incomplete"]) == (40, 40, 40, 0)
    assert all(count == 0 for count in s["mistakes"].values())


def test_the_always_stop_agent_gives_the_known_baseline():
    """Always-stop passes 3 stops, gives the wrong reason on 9, and over-abstains on all 28 non-stops."""
    s = summarise(run(always_stop))
    assert (s["passed"], s["stops"]) == (3, 12)
    assert s["mistakes"]["wrong_reason"] == 9
    assert s["mistakes"]["over_abstain"] == 28
    assert s["mistakes"]["wrong_outcome"] == 28
    assert s["mistakes"]["missed_stop"] == 0


def test_the_agent_sees_a_copy_of_the_ticket_and_never_the_answer_key():
    """A spy agent gets only ticket fields, and its edits to them do not reach the labels."""
    before = copy.deepcopy(KEYS)
    seen = []

    def spy(ticket):
        """Record what arrives, then vandalise it."""
        seen.append(set(ticket))
        ticket.clear()
        return {"outcome": "stop_and_ask", "reason": "free_text_conflict", "rules": []}

    # Check outside the agent: the runner turns anything raised inside it into agent_error.
    results = run(spy)
    assert len(seen) == 40
    assert seen == [set(r.ticket) for r in REQUESTS]
    assert not any("agent_error" in r.verdict.mistakes for r in results)
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
    assert (s["passed"], s["complete"], s["incomplete"]) == (40, 39, 1)


def test_a_wider_port_fails_as_too_wide():
    """Port 22 widened to 22-23 on RITM0011001 is excess access, so the ticket fails."""
    def widen(reply):
        """Open one extra port on the first rule."""
        reply["rules"][0]["ports"] = ["22-23"]
        return reply

    r = result_for(run(perfect_except("RITM0011001", widen)), "RITM0011001")
    assert not r.verdict.passed
    assert r.verdict.mistakes == ["too_wide"]


def test_drafting_an_already_allowed_ticket_fails_as_wrong_outcome():
    """RITM0011024 is already allowed; answering draft is the wrong outcome word."""
    def draft(reply):
        """Swap the outcome to draft."""
        reply["outcome"] = "draft"
        return reply

    r = result_for(run(perfect_except("RITM0011024", draft)), "RITM0011024")
    assert "wrong_outcome" in r.verdict.mistakes
    assert r.reply_outcome == "draft" and r.expected_outcome == "already_allowed"


def test_a_crash_fails_one_ticket_and_the_run_goes_on():
    """An exception on one ticket is agent_error there; the other 39 are still scored."""
    def crash(reply):
        """Fail the way a broken agent would."""
        raise RuntimeError("model timed out")

    results = run(perfect_except("RITM0011010", crash))
    assert len(results) == 40
    r = result_for(results, "RITM0011010")
    assert r.verdict.mistakes == ["agent_error"] and r.reply_outcome == "?"
    assert "RuntimeError: model timed out" in r.verdict.detail
    assert summarise(results)["complete"] == 39


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
    assert sum(total for _, total in rows) == s["tickets"] == 40
    assert sum(done for done, _ in rows) == s["complete"]
