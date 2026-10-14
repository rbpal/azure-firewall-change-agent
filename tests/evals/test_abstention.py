"""The Abstention scorer, on hand-written replies built from real labels. Every check here must be able to fail."""

import copy
from pathlib import Path

import pytest
import yaml

from evals.abstention import score_abstention

REQUESTS = Path(__file__).resolve().parents[2] / "evals" / "requests"
LABELS = {p.stem: yaml.safe_load(p.read_text())["expected"] for p in sorted(REQUESTS.glob("*/*.yaml"))}
STOPS = {k: v for k, v in LABELS.items() if v["outcome"] == "stop_and_ask"}
REASONS = sorted({v["reason"] for v in STOPS.values()})
DRAFT = LABELS["validation_RITM0011001"]
ALREADY = LABELS["validation_RITM0011024"]
STOP = LABELS["validation_RITM0011030"]  # env_mismatch


@pytest.mark.parametrize("name", LABELS)
def test_every_label_passes_as_its_own_reply(name):
    """A reply equal to the label stops exactly when it should, for the labelled reason."""
    score = score_abstention(LABELS[name], copy.deepcopy(LABELS[name]))
    assert score.result == "pass"
    assert score.kind == ("correct_stop" if name in STOPS else "correct_proceed")


@pytest.mark.parametrize("name", STOPS)
def test_a_stop_with_any_other_reason_fails(name):
    """Every other reason on the list is the wrong thing to tell the engineer."""
    for reason in REASONS:
        if reason != STOPS[name]["reason"]:
            score = score_abstention(STOPS[name], {"outcome": "stop_and_ask", "reason": reason, "rules": []})
            assert (score.result, score.kind) == ("fail", "wrong_reason")


@pytest.mark.parametrize("reason", [None, "", "ENV_MISMATCH"])
def test_a_stop_with_a_missing_or_misspelt_reason_fails(reason):
    """The reason must be exactly the labelled code."""
    score = score_abstention(STOP, {"outcome": "stop_and_ask", "reason": reason, "rules": []})
    assert score.kind == "wrong_reason"


@pytest.mark.parametrize("outcome", ["draft", "already_allowed", None])
def test_not_stopping_on_a_stop_label_is_a_missed_stop(outcome):
    """Drafting, calling it allowed or giving no outcome all miss the stop."""
    score = score_abstention(STOP, {"outcome": outcome, "rules": []})
    assert (score.result, score.kind) == ("fail", "missed_stop")


def test_a_stop_that_also_writes_rules_fails():
    """A stop must write nothing, even with the right reason."""
    out = {"outcome": "stop_and_ask", "reason": "env_mismatch", "rules": copy.deepcopy(DRAFT["rules"])}
    assert score_abstention(STOP, out).kind == "stop_with_rules"


@pytest.mark.parametrize("expected", [DRAFT, ALREADY], ids=["draft", "already_allowed"])
def test_stopping_when_the_label_proceeds_is_over_abstain(expected):
    """A needless stop fails, as its own kind, so the runner can count it apart from missed stops."""
    score = score_abstention(expected, {"outcome": "stop_and_ask", "reason": "env_mismatch", "rules": []})
    assert (score.result, score.kind) == ("fail", "over_abstain")


def test_the_stop_labels_cover_several_reasons():
    """The eval must test more than one reason, or wrong_reason is never exercised."""
    assert len(REASONS) >= 5
