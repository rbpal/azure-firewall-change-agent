"""The mutation list stays valid as the scorers and the runner change. Every check here must be able to fail."""

from pathlib import Path

import pytest

from evals.mutate_scorers import AB, LP, MUTATIONS, REPO, RUN, mutated


@pytest.mark.parametrize("m", MUTATIONS, ids=lambda m: m.name)
def test_every_mutation_matches_its_scorer_exactly_once(m):
    """If a mutated file is edited and a mutation no longer applies, this fails before CI's mutation run does."""
    assert (REPO / m.path).read_text().count(m.old) == 1


@pytest.mark.parametrize("m", MUTATIONS, ids=lambda m: m.name)
def test_every_mutation_changes_the_code(m):
    """A mutation that replaces text with itself proves nothing."""
    assert m.old != m.new


def test_mutation_names_are_unique_and_cover_scorers_and_runner():
    """Each line of output names one mutation, and both scorers and the runner are mutated."""
    assert len({m.name for m in MUTATIONS}) == len(MUTATIONS)
    assert {m.path for m in MUTATIONS} == {LP, AB, RUN}


def test_the_plans_three_mutations_are_listed():
    """Step 03 Task 03 names these three; each must be in the run."""
    names = {m.name for m in MUTATIONS}
    assert {"widen a port range", "drop the protocol comparison", "accept a guess as an answer"} <= names


def test_mutated_puts_the_original_back_even_on_error(tmp_path):
    """A failed run must never leave a broken scorer behind."""
    f = tmp_path / "scorer.py"
    f.write_text("x = 1\n")
    with pytest.raises(RuntimeError):
        with mutated(f, "x = 1", "x = 2"):
            assert f.read_text() == "x = 2\n"
            raise RuntimeError("boom")
    assert f.read_text() == "x = 1\n"


def test_mutated_refuses_text_that_is_missing(tmp_path):
    """Replacing text that is not there would silently test the unmutated code."""
    f = tmp_path / "scorer.py"
    f.write_text("x = 1\n")
    with pytest.raises(ValueError):
        with mutated(f, "y = 1", "y = 2"):
            pass
    assert f.read_text() == "x = 1\n"
