"""Engineer review: a ticket with a problem is kept as awaiting_review, never rejected, and the engineer edits, accepts or rejects it.

Each test runs fwagent on a copy of the env-site files. Every check here must be able to fail.
"""

import copy
import ipaddress
import json
import random
import re

import pytest
import yaml

import workflow.cli as cli
from workflow import intake
from workflow.tickets import SCHEMA_PATH as SCHEMA, ticket_errors
from tests.workflow.test_cli import ADD, ADD_FILE, REPO, changed, draft, files, repo, request, run, snapshot  # noqa: F401  (repo is a fixture)

ENGINEER = "Jordan Patel"


def version(repo):
    """The current ticket version, as the review note prints it (12 characters)."""
    return cli.load_record(repo, ADD)["ticket_version"][:12]


def ticket_with(tmp_path, name, **source):
    """RITM0011041 with its one source replaced; written to a YAML file whose path is returned."""
    t = copy.deepcopy(request(ADD)[0])
    t["sources"] = [{"environment": "stage", "site": "primary", **source}]
    path = tmp_path / f"{name}.yaml"
    path.write_text(yaml.safe_dump(t))
    return str(path), t


def reply_file(tmp_path, name, reply):
    """Write an agent reply to JSON; return its path."""
    path = tmp_path / f"{name}.json"
    path.write_text(json.dumps(reply))
    return str(path)


def label_reply(tmp_path):
    """The labelled draft for RITM0011041, as a reply file."""
    return reply_file(tmp_path, "label", request(ADD)[1])


def stop(tmp_path, reason):
    """RITM0011041 and a stop reply giving `reason`; draft() submits, accepts and gets that stop."""
    ticket, _ = files(tmp_path, ADD)
    reply = reply_file(tmp_path, "stop", {"outcome": "stop_and_ask", "reason": reason, "rules": []})
    return ticket, reply


# Intake: malformed or incomplete tickets are kept for review, never refused, never reach the agent.

@pytest.mark.parametrize("cidr, says", [
    ("172.20.20.0/33", "at most /32"),
    ("172.20.20.15/24", "the host 172.20.20.15/32 (1 address) or the subnet 172.20.20.0/24 (256 addresses)"),
    ("10.102.300.0/24", "0 to 255"),
])
def test_an_invalid_cidr_is_kept_for_review_with_its_explanation(repo, tmp_path, capsys, cidr, says):
    path, ticket = ticket_with(tmp_path, "bad", cidr=cidr)
    before = snapshot(repo)
    assert run(repo, "submit", path) == cli.REVIEW  # no --reply: the agent is never asked
    out = capsys.readouterr().out
    assert "invalid_address" in out and says in out and "needs an edit" in out
    assert "did you mean" not in out
    record = cli.load_record(repo, ADD)
    assert record["status"] == "awaiting_review" and record["reply"] is None
    assert record["original_ticket"] == ticket and record["ticket"]["sources"][0]["cidr"] == cidr  # never corrected
    if cidr == "172.20.20.15/24":
        assert record["findings"][0]["readings"] == ["172.20.20.15/32", "172.20.20.0/24"]  # both, neither chosen
    assert changed(before, repo) == set()


def address_ticket(tmp_path, side, cidr):
    """RITM0011041 with its one source, or its one destination, given `cidr`; written to YAML, path returned."""
    t = copy.deepcopy(request(ADD)[0])
    t[side] = [{"environment": "stage", "site": "primary", "cidr": cidr}] if side == "sources" else [{"cidr": cidr}]
    path = tmp_path / f"{side}.yaml"
    path.write_text(yaml.safe_dump(t))
    return str(path), t


NOT_A_CIDR = "is not written as an IPv4 CIDR"
INVALID_CIDRS = [
    ("256.1.2.3/32", "0 to 255"),  # each of the four octet positions
    ("1.256.2.3/32", "0 to 255"),
    ("1.2.256.3/32", "0 to 255"),
    ("1.2.3.256/32", "0 to 255"),
    ("1.2.3/24", NOT_A_CIDR),  # three octets
    ("1.2.3.4.5/32", NOT_A_CIDR),  # five octets
    ("1..3.4/32", NOT_A_CIDR),  # empty octet
    ("1.-2.3.4/32", NOT_A_CIDR),  # negative
    ("1.a.3.4/32", NOT_A_CIDR),  # not a number
    ("10.1.2.3", NOT_A_CIDR),  # no prefix: a host is written /32
    ("10.1.2.0/", NOT_A_CIDR),
    ("10.1.2.0/-1", NOT_A_CIDR),
    ("10.1.2.0/33", "at most /32"),
    ("10.1.2.0/100", "at most /32"),
    ("010.1.2.0/24", "leading zero"),
    ("10.1.02.0/24", "leading zero"),
    ("10.1.2.0/024", "leading zero"),  # Python's ipaddress would read this as /24 without a word
    ("10.1.2.0/24\n", NOT_A_CIDR),  # trailing newline
    (" 10.1.2.0/24", NOT_A_CIDR),  # leading space
    ("10.1.2.\u0660/24", NOT_A_CIDR),  # Arabic-Indic zero: a digit, but not an ASCII one
    ("172.20.20.15/24", "host bits set"),
]


@pytest.mark.parametrize("side", ["sources", "destination"])
@pytest.mark.parametrize("cidr, says", INVALID_CIDRS)
def test_a_malformed_address_waits_for_review_and_accept_never_reaches_the_agent(repo, tmp_path, monkeypatch, side, cidr, says):
    calls = []
    real = cli.read_reply
    monkeypatch.setattr(cli, "read_reply", lambda path: calls.append(path) or real(path))
    path, ticket = address_ticket(tmp_path, side, cidr)
    before = snapshot(repo)

    assert run(repo, "submit", path) == cli.REVIEW  # kept for the engineer, never a crash or a refusal
    record = cli.load_record(repo, ADD)
    assert record["status"] == "awaiting_review"
    [f] = record["findings"]
    assert (f["code"], f["where"], f["acceptable"]) == ("invalid_address", f"{side}/0/cidr", False)
    assert says in f["message"]
    assert record["ticket"] == record["original_ticket"] == ticket  # the address is never corrected

    assert run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "looks fine",
               "--reply", label_reply(tmp_path)) == cli.REFUSED  # the exact version, still refused
    assert calls == [] and cli.load_record(repo, ADD)["status"] == "awaiting_review"
    assert changed(before, repo) == set()


@pytest.mark.parametrize("side", ["sources", "destination"])
@pytest.mark.parametrize("cidr", ["0.0.0.0/0", "255.255.255.255/32", "10.255.0.0/16", "10.104.255.0/24",
                                  "203.0.113.255/32", "10.0.0.0/32", "0.0.0.0/32", "10.0.0.0/8"])
def test_octets_0_and_255_are_valid_syntax(tmp_path, side, cidr):
    # Syntax only. How wide a range may be, and whether the plan knows it, are checked later, not here.
    _, ticket = address_ticket(tmp_path, side, cidr)
    assert intake.cidr_finding(f"{side}/0/cidr", cidr) is None
    assert intake.intake_findings(REPO, ticket) == [] and ticket_errors(ticket) == []


def test_no_address_text_crashes_intake_and_it_agrees_with_the_schema():
    # 3,000 generated addresses mixing good and bad octets, prefixes, separators and characters.
    pattern = next(v["properties"]["cidr"]["pattern"] for v in _schema_nodes(json.loads(SCHEMA.read_text()))
                   if "cidr" in v.get("properties", {}))
    good_octets, bad_octets = ["0", "9", "10", "99", "100", "199", "249", "255"], \
        ["256", "300", "999", "00", "01", "010", "-1", "a", "", "\u0660"]
    good_prefixes, bad_prefixes = ["0", "8", "24", "32", "32"], ["33", "99", "-1", "00", "024", "", "24\n", "24 "]
    rng = random.Random(0)

    def pick(good, bad):
        """Mostly a well-formed part, so valid addresses are tested too, sometimes a malformed one."""
        return rng.choice(good if rng.random() < 0.85 else bad)

    valid_seen = 0
    for _ in range(3000):
        count = rng.choice([3, 4, 4, 4, 4, 4, 5])
        text = ".".join(pick(good_octets, bad_octets) for _ in range(count)) + "/" + pick(good_prefixes, bad_prefixes)
        found = intake.cidr_finding("sources/0/cidr", text)
        try:
            ipaddress.IPv4Network(text, strict=True)
            valid = re.fullmatch(pattern, text) is not None
        except ValueError:
            valid = False
        assert (found is None) == valid, text
        assert found is None or found["code"] == "invalid_address"
        valid_seen += valid
    assert valid_seen > 300  # both sides of the comparison are exercised


def _schema_nodes(node):
    """Every object in the JSON Schema, depth first."""
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from _schema_nodes(v)
    elif isinstance(node, list):
        for v in node:
            yield from _schema_nodes(v)


def test_a_vnet_without_an_address_is_kept_and_gets_no_guessed_cidr(repo, tmp_path, capsys):
    path, ticket = ticket_with(tmp_path, "vnet", vnet="vnet-prod-app", subnet="snet-backend")
    assert run(repo, "submit", path) == cli.REVIEW
    out = capsys.readouterr().out
    assert "missing_address" in out and "No VNet named vnet-prod-app" in out and "snet-backend cannot be mapped" in out
    assert cli.load_record(repo, ADD)["ticket"] == ticket


def test_a_known_vnet_name_is_shown_as_a_suggestion_with_its_source_never_applied(repo, tmp_path, capsys):
    path, _ = ticket_with(tmp_path, "vnet", vnet="vnet-rprt-stage")
    assert run(repo, "submit", path) == cli.REVIEW
    out = capsys.readouterr().out
    assert "suggestion, not applied: 10.102.15.0/24 vnet-rprt-stage stage primary (from data/network/address-plan.yaml)" in out
    assert "cidr" not in cli.load_record(repo, ADD)["ticket"]["sources"][0]


def test_a_vnet_prefix_matching_several_sites_lists_them_all_and_picks_none(repo, tmp_path, capsys):
    path, _ = ticket_with(tmp_path, "vnet", vnet="vnet-rprt")
    assert run(repo, "submit", path) == cli.REVIEW
    suggestions = cli.load_record(repo, ADD)["findings"][0]["suggestions"]
    assert len({(s["environment"], s["site"]) for s in suggestions}) > 1
    assert "none is applied" in capsys.readouterr().out


# Accept: refused while a value is invalid or missing; recorded, and scope-checked, when allowed.

@pytest.mark.parametrize("source", [{"cidr": "172.20.20.0/33"}, {"cidr": "10.102.15.7/24"}, {"vnet": "vnet-rprt-stage"}])
def test_accept_cannot_make_an_invalid_or_missing_address_executable(repo, tmp_path, capsys, source):
    path, _ = ticket_with(tmp_path, "bad", **source)
    run(repo, "submit", path)
    before = snapshot(repo)
    code = run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "looks fine", "--reply", label_reply(tmp_path))
    assert code == cli.REFUSED and "need an edit with a valid value" in capsys.readouterr().out
    assert cli.load_record(repo, ADD)["status"] == "awaiting_review"
    assert changed(before, repo) == set()


def test_accept_records_the_engineer_and_drafts_within_the_ticket(repo, tmp_path):
    ticket, reply = stop(tmp_path, "wider_than_plan")
    assert draft(repo, ticket, reply) == cli.REVIEW
    before = snapshot(repo)
    code = run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "Owner confirmed the /24", "--reply",
               label_reply(tmp_path))
    assert code == cli.DONE and changed(before, repo) == {ADD_FILE}
    record = cli.load_record(repo, ADD)
    assert record["status"] == "drafted"
    entry = record["history"][-1]
    assert entry["action"] == "accept" and entry["engineer"] == ENGINEER and entry["accepted"] == ["wider_than_plan"]
    assert entry["reason"] == "Owner confirmed the /24" and entry["at"]


def test_accept_never_adds_a_site_the_ticket_does_not_select(repo, tmp_path, capsys):
    ticket, reply = stop(tmp_path, "wider_than_plan")
    draft(repo, ticket, reply)
    wide = copy.deepcopy(request(ADD)[1])
    wide["rules"].append({**wide["rules"][0], "env_site": "stage-centralus", "sources": ["10.103.15.0/24"]})
    before = snapshot(repo)
    code = run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "ok", "--reply", reply_file(tmp_path, "w", wide))
    assert code == cli.REFUSED and "does not select" in capsys.readouterr().out
    assert changed(before, repo) == set()
    assert cli.load_record(repo, ADD)["status"] == "awaiting_review"  # the failed accept left no trace


@pytest.mark.parametrize("reason", ["env_mismatch", "free_text_conflict", "address_for_unselected_site"])
def test_a_contradiction_needs_an_edit_not_an_accept(repo, tmp_path, reason):
    ticket, reply = stop(tmp_path, reason)
    draft(repo, ticket, reply)
    assert run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "ok", "--reply", label_reply(tmp_path)) == cli.REFUSED


# Planned addresses: the engineer confirms CIDR, environment, site, policy and placement.

PLANNED = {"cidr": "10.102.15.0/24", "environment": "stage", "site": "primary",
           "firewall_policy": "afwp-hub-stage-eastus2", "spoke": "rprt", "placement": "rprt"}


def planned_file(tmp_path, *entries):
    """Write a planned-address record; return its path."""
    path = tmp_path / "planned.yaml"
    path.write_text(yaml.safe_dump(list(entries)))
    return str(path)


def test_accepting_a_planned_address_needs_the_planned_record(repo, tmp_path, capsys):
    ticket, reply = stop(tmp_path, "planned_address")
    draft(repo, ticket, reply)
    assert run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "ok", "--reply", label_reply(tmp_path)) == cli.REFUSED
    assert "--planned FILE" in capsys.readouterr().out


@pytest.mark.parametrize("change, says", [
    ({"cidr": "10.102.99.0/24"}, "not on the ticket"),
    ({"site": "dr"}, "not a site the ticket selects"),
    ({"firewall_policy": "afwp-hub-dev-eastus2"}, "uses policy afwp-hub-stage-eastus2"),
    ({"placement": "Reporting"}, "placement 'Reporting' is not a four-letter spoke name"),
    ({"spoke": "pay"}, "spoke 'pay' is not a four-letter spoke name"),
    ({"spoke": None, "extra": 1}, "needs exactly"),
])
def test_a_planned_record_that_does_not_fit_the_ticket_is_refused(repo, tmp_path, capsys, change, says):
    ticket, reply = stop(tmp_path, "planned_address")
    draft(repo, ticket, reply)
    before = snapshot(repo)
    code = run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "ok",
               "--planned", planned_file(tmp_path, {**PLANNED, **change}), "--reply", label_reply(tmp_path))
    assert code == cli.REFUSED and says in capsys.readouterr().out
    assert changed(before, repo) == set()


def test_a_planned_address_placed_in_an_existing_spoke_drafts(repo, tmp_path):
    ticket, reply = stop(tmp_path, "planned_address")
    draft(repo, ticket, reply)
    code = run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "Spoke built next sprint",
               "--planned", planned_file(tmp_path, PLANNED), "--reply", label_reply(tmp_path))
    assert code == cli.DONE
    record = cli.load_record(repo, ADD)
    assert record["status"] == "drafted" and record["review"]["planned"] == [PLANNED]


def test_a_planned_new_spoke_lists_what_is_missing_and_writes_nothing(repo, tmp_path, capsys):
    ticket, reply = stop(tmp_path, "planned_address")
    draft(repo, ticket, reply)
    before = snapshot(repo)
    code = run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "New payments spoke",
               "--planned", planned_file(tmp_path, {**PLANNED, "placement": "pymt"}))  # no --reply needed to wait
    assert code == cli.REVIEW and changed(before, repo) == set()
    record = cli.load_record(repo, ADD)
    assert record["status"] == "awaiting_platform_change"
    folder = "infra/envs/stage-eastus2"
    assert record["missing"] == [
        f"{folder}/firewall_policy_rule_collection_groups/pymt.tfvars: the rule collection group for spoke pymt",
        f'{folder}/variables.tf: variable "pymt"',
        f"{folder}/main.tf: pymt = var.pymt in the rules map",
        "data/network/routing.yaml: env_sites.stage-eastus2.spokes.pymt",
        "data/network/address-plan.yaml: range 10.102.15.0/24 for spoke pymt at stage-eastus2",
    ]
    assert "missing:" in capsys.readouterr().out
    assert record["history"][-1]["engineer"] == ENGINEER  # the acceptance is kept while it waits


# Edit: rerun every check on the engineer's values, and record what changed.

def test_an_edit_with_a_valid_cidr_reruns_the_checks_and_drafts(repo, tmp_path):
    bad, original = ticket_with(tmp_path, "bad", cidr="10.102.15.7/24")
    run(repo, "submit", bad)
    fixed, _ = ticket_with(tmp_path, "fixed", cidr="10.102.15.0/24")
    code = run(repo, "edit", ADD, fixed, "--engineer", ENGINEER, "--note", "Requester confirmed the subnet")
    assert code == cli.REVIEW  # checks pass, but the agent waits for acceptance of the edited version
    record = cli.load_record(repo, ADD)
    assert record["status"] == "awaiting_review" and record["findings"] == [] and record["reply"] is None
    entry = record["history"][-1]
    assert entry["engineer"] == ENGINEER and entry["note"] == "Requester confirmed the subnet"
    assert entry["changes"]["sources"]["before"][0]["cidr"] == "10.102.15.7/24"
    assert entry["changes"]["sources"]["after"][0]["cidr"] == "10.102.15.0/24"
    assert run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "confirmed",
               "--reply", label_reply(tmp_path)) == cli.DONE
    record = cli.load_record(repo, ADD)
    assert record["status"] == "drafted" and record["original_ticket"] == original


def test_an_edit_that_is_still_invalid_stays_in_review(repo, tmp_path):
    bad, _ = ticket_with(tmp_path, "bad", cidr="172.20.20.0/33")
    run(repo, "submit", bad)
    still, _ = ticket_with(tmp_path, "still", cidr="172.20.20.15/24")
    before = snapshot(repo)
    assert run(repo, "edit", ADD, still, "--engineer", ENGINEER, "--note", "try") == cli.REVIEW
    record = cli.load_record(repo, ADD)
    assert record["status"] == "awaiting_review" and "host bits" in record["findings"][0]["message"]
    assert changed(before, repo) == set()


@pytest.mark.parametrize("change", [{"state": "pending"}, {"approvals": []}, {"number": "RITM0011099"}])
def test_an_edit_cannot_change_approvals_state_or_number(repo, tmp_path, capsys, change):
    bad, _ = ticket_with(tmp_path, "bad", cidr="172.20.20.0/33")
    run(repo, "submit", bad)
    t = copy.deepcopy(request(ADD)[0])
    t.update(change)
    path = tmp_path / "edited.yaml"
    path.write_text(yaml.safe_dump(t))
    assert run(repo, "edit", ADD, str(path), "--engineer", ENGINEER, "--note", "x") == cli.REFUSED
    assert cli.load_record(repo, ADD)["history"][-1]["action"] == "submit"


def test_an_edit_is_saved_without_the_agent(repo, tmp_path):
    bad, _ = ticket_with(tmp_path, "bad", cidr="172.20.20.0/33")
    run(repo, "submit", bad)
    fixed, _ = ticket_with(tmp_path, "fixed", cidr="10.102.15.0/24")
    assert run(repo, "edit", ADD, fixed, "--engineer", ENGINEER, "--note", "x") == cli.REVIEW
    assert cli.load_record(repo, ADD)["ticket"]["sources"][0]["cidr"] == "10.102.15.0/24"


# Reject: closes the request without implementing it.

def test_reject_closes_a_ticket_awaiting_review_and_records_who(repo, tmp_path):
    bad, _ = ticket_with(tmp_path, "bad", cidr="172.20.20.0/33")
    run(repo, "submit", bad)
    before = snapshot(repo)
    assert run(repo, "reject", ADD, "Requester cannot give a valid range", "--engineer", ENGINEER) == cli.DONE
    record = cli.load_record(repo, ADD)
    assert record["status"] == "rejected" and record["history"][-1]["engineer"] == ENGINEER
    assert changed(before, repo) == set()


@pytest.mark.parametrize("command", [["accept", ADD, "--reason", "x", "--ticket-version", "0" * 12],
                                     ["edit", ADD, "TICKET", "--note", "x"]])
def test_edit_and_accept_need_a_ticket_awaiting_review(repo, tmp_path, capsys, command):
    ticket, reply = files(tmp_path, ADD)
    draft(repo, ticket, reply)  # drafted, not awaiting review
    capsys.readouterr()
    argv = [ticket if a == "TICKET" else a for a in command] + ["--engineer", ENGINEER]
    argv += ["--reply", reply] if command[0] == "accept" else []
    assert run(repo, *argv) == cli.REFUSED
    assert "the ticket is drafted, not awaiting review" in capsys.readouterr().out


def test_a_ticket_awaiting_review_cannot_be_submitted_again(repo, tmp_path, capsys):
    bad, _ = ticket_with(tmp_path, "bad", cidr="172.20.20.0/33")
    run(repo, "submit", bad)
    assert run(repo, "submit", bad) == cli.REFUSED
    assert "already awaiting_review" in capsys.readouterr().out


# Acceptance is bound to one ticket version.

def test_accept_names_the_version_on_the_review_note(repo, tmp_path, capsys):
    ticket, reply = stop(tmp_path, "wider_than_plan")
    draft(repo, ticket, reply)
    assert f"--ticket-version {version(repo)}" in capsys.readouterr().out
    run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "ok",
        "--reply", label_reply(tmp_path))
    record = cli.load_record(repo, ADD)
    assert record["review"]["ticket_version"] == record["ticket_version"] == record["history"][-1]["ticket_version"]


@pytest.mark.parametrize("given", ["0" * 12, "abc"])
def test_accept_with_another_or_a_too_short_version_is_refused(repo, tmp_path, capsys, given):
    ticket, reply = stop(tmp_path, "wider_than_plan")
    draft(repo, ticket, reply)
    if given == "abc":
        given = version(repo)[:3]  # a real prefix, but too short to identify a version
    before = snapshot(repo)
    code = run(repo, "accept", ADD, "--ticket-version", given, "--engineer", ENGINEER, "--reason", "ok",
               "--reply", label_reply(tmp_path))
    assert code == cli.REFUSED and "read the current review note" in capsys.readouterr().out
    assert changed(before, repo) == set() and cli.load_record(repo, ADD)["status"] == "awaiting_review"


def test_an_edit_makes_a_new_version_and_voids_an_earlier_acceptance(repo, tmp_path):
    ticket, reply = stop(tmp_path, "planned_address")
    draft(repo, ticket, reply)
    old = version(repo)
    run(repo, "accept", ADD, "--ticket-version", old, "--engineer", ENGINEER, "--reason", "New spoke",
        "--planned", planned_file(tmp_path, {**PLANNED, "placement": "pymt"}))
    assert cli.load_record(repo, ADD)["status"] == "awaiting_platform_change"
    t = copy.deepcopy(request(ADD)[0])
    t["justification"] += " Edited."
    path = tmp_path / "edited.yaml"
    path.write_text(yaml.safe_dump(t))
    run(repo, "edit", ADD, str(path), "--engineer", ENGINEER, "--note", "wording")
    record = cli.load_record(repo, ADD)
    assert record["ticket_version"][:12] != old and "review" not in record
    assert run(repo, "accept", ADD, "--ticket-version", old, "--engineer", ENGINEER, "--reason", "again",
               "--planned", planned_file(tmp_path, PLANNED), "--reply", label_reply(tmp_path)) == cli.REFUSED


# The agent runs only after the engineer accepts the exact ticket version, even for a clean ticket.

def test_a_clean_ticket_makes_zero_agent_calls_until_its_exact_version_is_accepted(repo, tmp_path, monkeypatch):
    calls = []
    real = cli.read_reply

    def counted(path):
        """The replay stand-in is the agent: count every call to it."""
        calls.append(path)
        return real(path)

    monkeypatch.setattr(cli, "read_reply", counted)
    ticket, reply = files(tmp_path, ADD)
    before = snapshot(repo)

    assert run(repo, "submit", ticket) == cli.REVIEW  # no findings, still waits
    record = cli.load_record(repo, ADD)
    assert record["findings"] == [] and record["status"] == "awaiting_review" and calls == []
    first = version(repo)

    t = copy.deepcopy(request(ADD)[0])
    t["justification"] += " Confirmed with the requester."
    edited = tmp_path / "edited.yaml"
    edited.write_text(yaml.safe_dump(t))
    assert run(repo, "edit", ADD, str(edited), "--engineer", ENGINEER, "--note", "wording") == cli.REVIEW
    assert calls == [] and version(repo) != first  # an edit makes a new version and still no agent call

    for wrong in (first, "0" * 12, version(repo)[:5]):  # the old version, another version, too short
        assert run(repo, "accept", ADD, "--ticket-version", wrong, "--engineer", ENGINEER, "--reason", "ok",
                   "--reply", reply) == cli.REFUSED
    assert calls == [] and changed(before, repo) == set()

    assert run(repo, "accept", ADD, "--ticket-version", version(repo), "--engineer", ENGINEER, "--reason", "ok",
               "--reply", reply) == cli.DONE
    assert calls == [reply]  # exactly one agent call, after acceptance of the exact version
    record = cli.load_record(repo, ADD)
    assert record["status"] == "drafted" and record["review"]["ticket_version"] == record["ticket_version"]
    assert changed(before, repo) == {ADD_FILE}
