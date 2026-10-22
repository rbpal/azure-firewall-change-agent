"""The Tier 2 runner, checked with stand-in agents on the 66 validation tickets. Every check here must be able to fail."""

import copy

import pytest

from evals.run_eval import TicketResult, Verdict, format_report, load_requests, main, run, summarise
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
    assert reviews == [r.engineer_review for r in REQUESTS]  # the engineer's decision, when there is one
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
