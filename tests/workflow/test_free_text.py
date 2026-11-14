"""Free text that names another environment: intake holds the ticket, and an accept covers only what it quotes.

Every ticket here is made up for the test. None is an eval ticket, and no eval answer is read or changed.
"""

import copy

import pytest
import yaml

import workflow.cli as cli
from workflow.intake import free_text_findings
from tests.workflow.test_cli import ADD, ADD_FILE, changed, request, run, snapshot  # noqa: F401
from tests.workflow.test_cli import repo  # noqa: F401  (a fixture)
from tests.workflow.test_review import ENGINEER, label_reply, version

CONFLICT = "free_text_conflict"


def made_up(justification, environments=("lab",)):
    """A made-up ticket holding only the two fields the free-text check reads."""
    return {"justification": justification, "environments": list(environments)}


def found(justification, environments=("lab",)):
    """The environments the check reports for a made-up ticket, in the order they appear."""
    return [f["environment"] for f in free_text_findings(made_up(justification, environments))]


@pytest.mark.parametrize("text, selected", [
    ("Needed in lab before the release.", ["lab"]),
    ("The dev servers send files.", ["dev"]),
    ("No environment named here.", ["prod"]),
])
def test_free_text_that_agrees_with_the_fields_gives_no_finding(text, selected):
    assert found(text, selected) == []


def test_free_text_that_names_another_environment_is_held_with_the_text_and_the_fields():
    [f] = free_text_findings(made_up("Needed in dev before the dev release next week."))
    assert (f["code"], f["where"], f["acceptable"]) == (CONFLICT, "justification", True)
    assert (f["matched"], f["environment"], f["selected"]) == (["dev"], "dev", ["lab"])
    assert '"dev"' in f["message"] and "selects lab" in f["message"]


@pytest.mark.parametrize("word, environment", [
    ("development", "dev"), ("staging", "stage"), ("production", "prod"), ("stage", "stage"), ("prod", "prod")])
def test_each_alias_counts_as_its_environment(word, environment):
    assert found(f"Needed in {word} first.", ["lab"]) == [environment]
    assert found(f"Needed in {word} first.", [environment]) == []  # the alias agrees with its own environment


@pytest.mark.parametrize("text", ["Needed in PROD.", "Needed in Prod.", "Staging first.", "(dev)", "dev-eastus2 first."])
def test_matching_ignores_case_and_punctuation(text):
    assert found(text, ["lab"]) != []


@pytest.mark.parametrize("text", ["The device team asks.", "Our devops pipeline.", "Products ship.", "The prodigy job.",
                                  "A stagecoach export.", "The developer laptops.", "The labs building."])
def test_a_word_only_containing_an_environment_name_is_not_a_match(text):
    assert found(text, ["lab" if "lab" not in text else "dev"]) == []


def test_several_selected_environments_are_all_respected():
    assert found("Needed in dev and in prod.", ["dev", "prod"]) == []
    [f] = free_text_findings(made_up("Needed in dev, prod and staging.", ["dev", "prod"]))
    assert (f["environment"], f["matched"], f["selected"]) == ("stage", ["staging"], ["dev", "prod"])


def test_two_discrepancies_give_two_findings_each_quoting_its_own_words():
    out = free_text_findings(made_up("Needed in Production and dev; prod first.", ["lab"]))
    assert [(f["environment"], f["matched"]) for f in out] == [("prod", ["Production", "prod"]), ("dev", ["dev"])]


def test_a_missing_or_malformed_field_is_left_to_the_schema_check():
    assert free_text_findings({"environments": ["lab"]}) == []
    assert free_text_findings({"justification": "dev", "environments": "lab"}) == []


# Through fwagent: hold, accept that exact discrepancy, and lose the accept on any edit.

def submit(repo, tmp_path, name, justification):
    """Submit a made-up copy of the stage ticket with this justification; return its exit code and ticket."""
    t = copy.deepcopy(request(ADD)[0])
    t["justification"] = justification
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(t))
    return run(repo, "submit", str(path)), t, str(path)


def test_a_conflict_holds_the_ticket_unchanged_and_writes_nothing(repo, tmp_path):
    before = snapshot(repo)
    code, t, _ = submit(repo, tmp_path, "held", "Needed in prod before the release.")
    record = cli.load_record(repo, ADD)
    assert code == cli.REVIEW and record["status"] == "awaiting_review" and record["reply"] is None
    assert [(f["code"], f["environment"]) for f in record["findings"]] == [(CONFLICT, "prod")]
    assert record["ticket"] == t  # never edited
    assert changed(before, repo) == set()


def test_the_engineer_can_accept_and_the_acceptance_quotes_the_discrepancy(repo, tmp_path):
    submit(repo, tmp_path, "held", "Needed in prod before the release.")
    [f] = cli.load_record(repo, ADD)["findings"]
    before = snapshot(repo)
    code = run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER,
               "--reason", "The fields are right: stage only", "--reply", label_reply(tmp_path))
    record = cli.load_record(repo, ADD)
    assert code == cli.DONE and record["status"] == "drafted" and changed(before, repo) == {ADD_FILE}
    review = record["review"]
    assert review["accepted"] == [CONFLICT]
    assert review["discrepancies"] == [{k: f[k] for k in ("code", "where", "message", "matched", "environment",
                                                           "selected")}]
    assert review["ticket_version"] == record["ticket_version"]


def test_an_acceptance_without_a_free_text_finding_has_no_discrepancies_field():
    assert "discrepancies" not in cli.acceptance("v", ENGINEER, "ok", ["wider_than_plan"])


def test_an_edit_voids_the_acceptance_and_a_new_discrepancy_needs_its_own_accept(repo, tmp_path):
    submit(repo, tmp_path, "held", "Needed in prod before the release.")
    old = version(repo)
    t = copy.deepcopy(request(ADD)[0])
    t["justification"] = "Needed in prod before the release, and in dev later."
    path = tmp_path / "edited.yaml"
    path.write_text(yaml.safe_dump(t))
    assert run(repo, "edit", ADD, str(path), "--engineer", ENGINEER, "--note", "added dev") == cli.REVIEW
    record = cli.load_record(repo, ADD)
    assert "review" not in record and [f["environment"] for f in record["findings"]] == ["prod", "dev"]
    assert run(repo, "accept", ADD, "--ticket-version", old, "--engineer", ENGINEER, "--reason", "again",
               "--reply", label_reply(tmp_path)) == cli.REFUSED  # the accept for the old version covers nothing now
    assert run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "both",
               "--reply", label_reply(tmp_path)) == cli.DONE
    assert [d["environment"] for d in cli.load_record(repo, ADD)["review"]["discrepancies"]] == ["prod", "dev"]


def test_an_agent_stop_for_a_site_or_location_conflict_can_be_accepted_with_its_explanation(repo, tmp_path):
    ticket = tmp_path / "t.yaml"
    ticket.write_text(yaml.safe_dump(request(ADD)[0]))
    stop = tmp_path / "stop.json"
    stop.write_text('{"outcome": "stop_and_ask", "reason": "free_text_conflict", "rules": [], '
                    '"explanation": "The justification says DR, but the ticket selects the primary site only."}')
    assert run(repo, "submit", str(ticket)) == cli.REVIEW
    assert run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "c",
               "--reply", str(stop)) == cli.REVIEW
    assert run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER,
               "--reason", "Primary only is right", "--reply", label_reply(tmp_path)) == cli.DONE
    [d] = cli.load_record(repo, ADD)["review"]["discrepancies"]
    assert (d["where"], d["message"]) == ("(agent)", "The justification says DR, but the ticket selects the primary site only.")
