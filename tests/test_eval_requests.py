"""The labelled requests and the script that writes their tickets. Every check here must be able to fail."""

import collections
from pathlib import Path

import pytest
import yaml

from evals import make_requests
from workflow.tickets import ticket_errors

REQUESTS = make_requests.REQUESTS
COMMITTED = sorted(REQUESTS.glob("*/*.yaml"))
STOP_CATEGORIES = {
    "dr-answer-contradicts-sources", "address-environment-contradicts-ticket",
    "address-not-in-plan", "free-text-names-another-environment",
}
OUTCOMES = {"draft", "stop_and_ask", "already_allowed"}
STOP_REASONS = {
    "dr_yes_no_source", "dr_no_but_dr_source", "env_mismatch",
    "address_not_in_plan", "dr_policy_not_built", "free_text_conflict",
}
RULE_FIELDS = {"env_site", "spoke", "collection", "name", "sources", "destinations", "ports", "protocol"}


def load(path):
    """Read one request file."""
    return yaml.safe_load(Path(path).read_text())


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    """Run the script once into a temporary folder."""
    out = tmp_path_factory.mktemp("requests")
    make_requests.write(out)
    return out


def test_script_writes_the_planned_mix(generated):
    counts = collections.Counter((p.parent.name, load(p)["category"]) for p in generated.glob("*/*.yaml"))
    for name, n_validation, n_test in make_requests.CATEGORIES:
        assert counts[("validation", name)] == n_validation, name
        assert counts[("test", name)] == n_test, name
    assert sum(v for (split, _), v in counts.items() if split == "validation") == 40
    assert sum(v for (split, _), v in counts.items() if split == "test") == 20


def test_every_generated_ticket_passes_the_schema(generated):
    for path in generated.glob("*/*.yaml"):
        assert ticket_errors(load(path)["ticket"]) == [], path.name


def test_script_writes_no_label(generated):
    for path in generated.glob("*/*.yaml"):
        assert load(path)["expected"] is None, path.name


def test_script_gives_the_same_output_every_run(generated, tmp_path):
    make_requests.write(tmp_path)
    for path in generated.glob("*/*.yaml"):
        assert (tmp_path / path.parent.name / path.name).read_text() == path.read_text(), path.name


def test_script_never_overwrites_a_file(tmp_path):
    make_requests.write(tmp_path)
    path = next(tmp_path.glob("validation/*.yaml"))
    path.write_text(path.read_text().replace("expected: null", "expected: {outcome: draft}"))
    written, kept = make_requests.write(tmp_path)
    assert written == [] and len(kept) == 60
    assert "expected: {outcome: draft}" in path.read_text()


def test_draft_requests_never_share_a_spoke_and_partner(generated):
    # A near copy in the other split would leak tuning into the test score.
    seen = {}
    for path in sorted(generated.glob("*/*.yaml")):
        request = load(path)
        if request["category"] in STOP_CATEGORIES or request["category"] == "address-not-in-plan":
            continue
        t = request["ticket"]
        internal = t["destination"] if request["category"] == "inbound-dnat" else t["sources"]
        key = (internal[0]["cidr"].split(".")[2], t["partner"])
        assert key not in seen, f"{path.name} repeats {seen.get(key)}"
        seen[key] = path.name


def test_removal_requests_use_the_removal_item(generated):
    for path in generated.glob("*/*.yaml"):
        request = load(path)
        removal = request["ticket"]["item"] == "Firewall Rule Removal"
        assert removal == (request["category"] == "removal"), path.name


def test_there_are_60_committed_requests():
    assert len(COMMITTED) == 60


@pytest.mark.parametrize("path", COMMITTED, ids=lambda p: p.name)
def test_file_name_matches_its_folder_and_number(path):
    request = load(path)
    split = path.parent.name
    assert path.name == f"{split}_{request['id']}.yaml"
    assert request["id"] == request["ticket"]["number"]
    assert request["id"].startswith(f"RITM00{make_requests.SPLITS[split]}")


@pytest.mark.parametrize("path", COMMITTED, ids=lambda p: p.name)
def test_committed_ticket_still_matches_the_script(path, generated):
    # Fails when someone edits a ticket by hand, or when the network data
    # changes under it; then the label must be checked again.
    fresh = load(generated / path.parent.name / path.name)
    committed = load(path)
    for key in ("id", "category", "why", "ticket"):
        assert committed[key] == fresh[key], key


@pytest.mark.parametrize("path", COMMITTED, ids=lambda p: p.name)
def test_label_has_the_agreed_shape(path):
    expected = load(path)["expected"]
    if expected is None:
        pytest.skip("not labelled yet")
    assert expected["outcome"] in OUTCOMES
    if expected["outcome"] == "stop_and_ask":
        assert expected["reason"] in STOP_REASONS
        assert expected.get("rules", []) == []
    else:
        assert expected["rules"], "a draft or already_allowed label names its rules"
        for rule in expected["rules"]:
            assert set(rule) == RULE_FIELDS
