"""The labelled requests and the script that writes their tickets. Every check here must be able to fail."""

import collections
from pathlib import Path

import pytest
import yaml

from evals import make_requests
from workflow.tfvars_writer import parse_rules
from workflow.tickets import ticket_errors

REQUESTS = make_requests.REQUESTS
COMMITTED = sorted(REQUESTS.glob("*/*.yaml"))
STOP_CATEGORIES = {
    "sites-contradict-addresses", "address-environment-contradicts-ticket",
    "address-not-in-plan", "free-text-names-another-environment",
    "onprem-address-not-in-plan", "onprem-location-mismatch", "wider-than-plan", "planned-spoke",
    "dnat-open-source", "dnat-destination-not-one-host", "onprem-to-onprem", "ip-group-not-found", "url-not-valid", "dns-lookup-failed",
    "non-http-to-hostname", "removal-rule-allows-more", "removal-hub-rule", "removal-asks-ip-group-change",
    "removal-one-site-matches",
}
OUTCOMES = {"draft", "stop_and_ask", "already_allowed"}
STOP_REASONS = {
    "site_without_address", "address_for_unselected_site", "env_mismatch",
    "address_not_in_plan", "dr_policy_not_built", "free_text_conflict",
    "skip_approval_requested",  # RB-01-6
    "port_already_published",  # RB-02-5
    "wider_than_plan", "planned_address",  # RB-01-6, decided 2026-10-20
}
CODED_2026_10_21 = {  # the escalations that had no code, each with a validation case
    "open_dnat_source", "dnat_destination_not_host",  # RB-02-5
    "both_ends_onprem",  # RB-05-5
    "ip_group_not_found", "dns_lookup_failed", "non_http_to_hostname",  # RB-01-6
    "rule_allows_more", "hub_rule", "ip_group_change_requested", "partial_site_match",  # RB-03-5
}
STOP_REASONS |= CODED_2026_10_21
RUNBOOKS = make_requests.REPO / "data" / "runbooks"
RULE_FIELDS = {"env_site", "spoke", "collection", "name", "sources", "destinations", "ports", "protocol"}
DNAT_FIELDS = RULE_FIELDS | {"translated_address", "translated_port"}  # inbound rules also name the internal host


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
    retired = collections.Counter(c for split, n, c, *_ in make_requests.plan() if n in make_requests.RETIRED)
    for name, n_validation, n_test in make_requests.CATEGORIES:
        assert counts[("validation", name)] == n_validation - retired[name], name
        assert counts[("test", name)] == n_test, name
    assert sum(v for (split, _), v in counts.items() if split == "validation") == 66
    assert sum(v for (split, _), v in counts.items() if split == "test") == 34


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
    assert written == [] and len(kept) == 100
    assert "expected: {outcome: draft}" in path.read_text()


def test_draft_requests_never_share_a_spoke_and_partner_across_splits(generated):
    # A near copy in the other split would leak tuning into the test score.
    # Within one split a pair may repeat (the one-sided cases of 2026-10-18).
    seen = {}
    for path in sorted(generated.glob("*/*.yaml")):
        request = load(path)
        if request["category"] in STOP_CATEGORIES or request["category"] == "address-not-in-plan":
            continue
        t = request["ticket"]
        internal = t["destination"] if request["category"] == "inbound-dnat" else t["sources"]
        first = internal[0]
        key = (first["cidr"].split(".")[2] if "cidr" in first else first["ip_group"], t["partner"])
        if t["partner"] is None:  # on-prem and spoke-to-spoke flows: the destination tells them apart
            dest = t["destination"][0]
            key += (dest.get("cidr") or dest.get("ip_group"),)
        split = path.parent.name
        assert seen.get(key, (split,))[0] == split, f"{path.name} repeats {seen[key][1]} from the other split"
        seen.setdefault(key, (split, path.name))


def test_removal_requests_use_the_removal_item(generated):
    for path in generated.glob("*/*.yaml"):
        request = load(path)
        removal = request["ticket"]["item"] == "Firewall Rule Removal"
        assert removal == request["category"].startswith("removal"), path.name


@pytest.mark.parametrize("scope", ["primary", "dr", "both"])
@pytest.mark.parametrize("item", ["Firewall Change Request", "Firewall Rule Removal"])
def test_every_scope_has_eval_cases_for_adds_and_removals(scope, item):
    want = {"primary": ["primary"], "dr": ["dr"], "both": ["primary", "dr"]}[scope]
    found = [p.name for p in COMMITTED
             if load(p)["ticket"]["item"] == item and load(p)["expected"]["outcome"] == "draft"
             and list(load(p)["ticket"]["change_sites"].values()) == [want]]
    assert len(found) >= 2, f"{item} with {scope} scope: {found}"


def test_there_are_100_committed_requests():
    assert len(COMMITTED) == 100


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
    for key in ("id", "category", "why", "ticket", "engineer_review", "dns"):
        assert committed.get(key) == fresh.get(key), key


@pytest.mark.parametrize("path", COMMITTED, ids=lambda p: p.name)
def test_label_has_the_agreed_shape(path):
    expected = load(path)["expected"]
    if expected is None:
        pytest.skip("not labelled yet")
    # `review: pending` marks a key no person has checked yet; deleting the line marks it reviewed.
    assert expected.get("review", "pending") == "pending"
    assert expected["outcome"] in OUTCOMES
    if expected["outcome"] == "stop_and_ask":
        assert expected["reason"] in STOP_REASONS
        assert expected.get("rules", []) == []
    else:
        assert expected["rules"], "a draft or already_allowed label names its rules"
        for rule in expected["rules"]:
            dnat = rule["collection"].endswith("-dnat-rules")
            assert set(rule) == (DNAT_FIELDS if dnat else RULE_FIELDS)


REGION = {"primary": "eastus2", "dr": "centralus"}


# Only a draft changes files. Listed here rather than skipped, so a stop or already_allowed
# label is not counted as a skipped test (until 2026-10-22 each one was, 36 of the 39 skips).
DRAFTS = [p for p in COMMITTED if (load(p)["expected"] or {}).get("outcome") == "draft"]


def test_the_draft_list_holds_every_draft_label():
    assert len(DRAFTS) == 63


@pytest.mark.parametrize("path", DRAFTS, ids=lambda p: p.name)
def test_label_rules_touch_exactly_the_selected_sites(path):
    # A primary-only ticket names no DR rule, even when DR is built, and the other way round.
    request = load(path)
    expected = request["expected"]
    selected = {f"{env}-{REGION[site]}" for env, sites in request["ticket"]["change_sites"].items() for site in sites}
    assert {r["env_site"] for r in expected["rules"]} == selected


def test_every_request_is_labelled():
    unlabelled = [p.name for p in COMMITTED if load(p)["expected"] is None]
    assert unlabelled == []


def _file_sources(env_site, spoke, name):
    """How the committed rule writes its source: ("source_ip_groups" or "source_addresses", values)."""
    path = Path("infra/envs") / env_site / "firewall_policy_rule_collection_groups" / f"{spoke}.tfvars"
    text = (make_requests.REPO / path).read_text()
    for c in parse_rules(text, spoke, str(path))["collections"]:
        for rule in c["rules"]:
            if rule["name"].strip('"') == name:
                field = "source_ip_groups" if "source_ip_groups" in rule else "source_addresses"
                return field, [v.strip('"') for v in rule[field]]
    raise AssertionError(f"{name} is not in {path}")


REMOVALS = [p for p in COMMITTED if (load(p)["expected"] or {}).get("action") == "remove"]


@pytest.mark.parametrize("path", REMOVALS, ids=lambda p: p.name)
def test_a_removal_label_keeps_the_source_form_its_rule_uses(path):
    # An IP group and the address it holds resolve the same, but the label copies the file:
    # a rule written with source_ip_groups is labelled by group name, one with source_addresses by address.
    for rule in load(path)["expected"]["rules"]:
        field, values = _file_sources(rule["env_site"], rule["spoke"], rule["name"])
        assert rule["sources"] == values, f"{rule['env_site']} {rule['name']}: file has {field} = {values}"


def test_validation_removals_cover_ip_group_and_address_sources():
    forms = {_file_sources(r["env_site"], r["spoke"], r["name"])[0]
             for p in REMOVALS if p.parent.name == "validation" for r in load(p)["expected"]["rules"]}
    assert forms == {"source_ip_groups", "source_addresses"}


def test_retired_numbers_are_never_written(generated):
    names = {p.stem.split("_")[1] for p in generated.glob("*/*.yaml")}
    assert make_requests.RETIRED and not names & make_requests.RETIRED


def documented_codes():
    """The stop-reason codes the runbooks' escalation lists give, from lines ending ": `code`"."""
    import re
    codes = set()
    for page in sorted(RUNBOOKS.glob("*.md")):
        for section in re.split(r"^(?=## )", page.read_text(), flags=re.M):
            if "Escalate instead of drafting when" in section.splitlines()[0]:
                codes |= set(re.findall(r"^- .*?: `([a-z_]+)`", section, re.M))
    return codes


def test_every_stop_reason_is_documented_in_a_runbook_and_no_other():
    # The agent learns the codes from the runbooks; a label must never use one they do not give.
    assert documented_codes() == STOP_REASONS


def test_every_label_reason_is_documented():
    reasons = {(load(p)["expected"] or {}).get("reason") for p in COMMITTED} - {None}
    assert reasons <= documented_codes()


UNCODED_ESCALATIONS = 4  # 2026-10-21, was 15; lower it as each escalation gets a code, never raise it


def test_uncoded_escalations_only_shrink():
    # Each must get a code before the agent's reply contract is final (Step 04 Task 03).
    count = sum(page.read_text().count(": *no code yet*") for page in RUNBOOKS.glob("*.md"))
    assert count <= UNCODED_ESCALATIONS


def test_every_code_added_on_2026_10_21_has_a_validation_case_and_no_test_case():
    # The test split is held out and was not touched: these codes are measured on validation only.
    reasons = {(p.parent.name, (load(p)["expected"] or {}).get("reason")) for p in COMMITTED}
    assert {code for split, code in reasons if split == "validation"} >= CODED_2026_10_21
    assert not {code for split, code in reasons if split == "test"} & CODED_2026_10_21


def test_open_dnat_is_one_escalation_in_the_dnat_runbook():
    # RB-01-6 once repeated RB-02-5's open-DNAT line, so one condition was counted twice.
    import re
    pages = [page.name for page in sorted(RUNBOOKS.glob("*.md"))
             for section in re.split(r"^(?=## )", page.read_text(), flags=re.M)
             if "Escalate instead of drafting when" in section.splitlines()[0]
             for line in section.splitlines() if line.startswith("- ") and "STD-COLL-04" in line]
    assert pages == ["inbound-dnat.md"]


REVIEW_KEYS = {"decision", "engineer", "reason", "ticket_version", "accepted", "planned"}


@pytest.mark.parametrize("path", COMMITTED, ids=lambda p: p.name)
def test_an_engineer_review_block_holds_the_decision_and_never_the_answer(path):
    # The runner hands this block to the agent, so it must carry the engineer's input only.
    from workflow.intake import ACCEPTABLE, ticket_version
    from workflow.planned import check_planned
    request = load(path)
    review = request.get("engineer_review")
    if request["category"] != "accepted-after-review":
        assert review is None
        return
    assert set(review) == REVIEW_KEYS and review["decision"] == "accept" and review["engineer"] and review["reason"]
    assert review["accepted"] and set(review["accepted"]) <= ACCEPTABLE
    assert review["ticket_version"] == ticket_version(request["ticket"])  # bound to this exact ticket
    assert check_planned(make_requests.REPO, request["ticket"], review["planned"]) == []
    assert ("planned_address" in review["accepted"]) == bool(review["planned"])
    assert request["expected"]["outcome"] == "draft"  # accepted, so the agent drafts within the ticket


@pytest.mark.parametrize("path", COMMITTED, ids=lambda p: p.name)
def test_every_eval_ticket_passes_intake(path):
    # Intake cases (invalid prefix, host bits, missing address, schema errors) are software tests in
    # tests/workflow/test_review.py; the agent never sees them, so no eval request may hold one.
    from workflow.intake import intake_findings
    assert intake_findings(make_requests.REPO, load(path)["ticket"]) == []


def test_every_accepted_category_is_a_draft_and_every_review_stop_has_no_acceptance():
    # Awaiting review (a stop, no engineer_review) and accepted for the agent (engineer_review, draft) never mix.
    for path in COMMITTED:
        request = load(path)
        if request["expected"]["outcome"] == "stop_and_ask":
            assert "engineer_review" not in request, path.name
        if "engineer_review" in request:
            assert request["expected"]["outcome"] == "draft", path.name
