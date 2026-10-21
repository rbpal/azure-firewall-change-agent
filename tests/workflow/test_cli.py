"""fwagent submit, fix, reject and approve, on a copy of the env-site files. Every check here must be able to fail.

Engineer review (edit, accept, reject while awaiting review) is in test_review.py."""

import copy
import json
import shutil
from pathlib import Path

import pytest
import yaml

import workflow.cli as cli
from workflow.scope import BACKUP, BackupsRemainError, apply_reply

REPO = Path(__file__).resolve().parents[2]
REQUESTS = REPO / "evals" / "requests" / "validation"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    """A copy of the network data and env-site files, with draft records kept in tmp_path/state."""
    root = tmp_path / "repo"
    shutil.copytree(REPO / "data" / "network", root / "data" / "network")
    shutil.copytree(REPO / "infra" / "envs", root / "infra" / "envs")
    monkeypatch.setenv("FWAGENT_STATE_DIR", str(tmp_path / "state"))
    return root


def snapshot(root):
    """Every file under infra/, as bytes, keyed by its path inside the copy."""
    return {p.relative_to(root): p.read_bytes() for p in sorted((root / "infra").rglob("*")) if p.is_file()}


def changed(before, root):
    """The files added, removed or changed since the snapshot."""
    after = snapshot(root)
    return {str(p) for p in before.keys() | after.keys() if before.get(p) != after.get(p)}


def request(number):
    """One labelled validation request: (ticket, labelled answer)."""
    data = yaml.safe_load((REQUESTS / f"validation_{number}.yaml").read_text())
    return data["ticket"], data["expected"]


def files(tmp_path, number, reply=None, ticket=None):
    """Write the ticket YAML and the reply JSON for a request; return their paths as strings."""
    t, e = request(number)
    tp, rp = tmp_path / f"{number}.yaml", tmp_path / f"{number}.reply.json"
    tp.write_text(yaml.safe_dump(ticket or t))
    rp.write_text(json.dumps(reply or e))
    return str(tp), str(rp)


def run(repo, *argv):
    """Run one fwagent command against the copy; return its exit code."""
    return cli.main(list(argv), repo=repo)


ADD = "RITM0011041"  # stage primary only, DR built: one new rule in stage-eastus2 rprt
ADD_FILE = "infra/envs/stage-eastus2/firewall_policy_rule_collection_groups/rprt.tfvars"
REMOVE = "RITM0011045"  # lab primary only: remove 008-smtp-sett-to-wingtipSmtp; lab DR keeps it
REMOVE_FILE = "infra/envs/lab-eastus2/firewall_policy_rule_collection_groups/sett.tfvars"


@pytest.mark.parametrize("number, file, key", [(ADD, ADD_FILE, "007-https-rprt-to-fourthcoffeeFs"),
                                               (REMOVE, REMOVE_FILE, "008-smtp-sett-to-wingtipSmtp")])
def test_submit_writes_only_the_selected_file_and_keeps_a_record(repo, tmp_path, capsys, number, file, key):
    ticket, reply = files(tmp_path, number)
    before = snapshot(repo)
    assert run(repo, "submit", ticket, "--reply", reply) == cli.DONE
    assert changed(before, repo) == {file}
    out = capsys.readouterr().out
    assert key in out and "Not run yet: Tier 1" in out
    record = cli.load_record(repo, number)
    assert record["status"] == "drafted" and record["keys"] == [{"file": file, "key": key}]
    assert record["files"][file]["before"].encode() == before[Path(file)]


def test_without_a_reply_submit_says_no_model_is_configured(repo, tmp_path, capsys):
    ticket, _ = files(tmp_path, ADD)
    before = snapshot(repo)
    assert run(repo, "submit", ticket) == cli.REFUSED
    assert "Step 04 Task 03" in capsys.readouterr().out
    assert changed(before, repo) == set()


def test_an_unapproved_ticket_is_out_of_scope_and_writes_nothing(repo, tmp_path, capsys):
    # Every ticket is assumed approved in ServiceNow before it arrives; anything else is refused at the door.
    t = copy.deepcopy(request(ADD)[0])
    t.update(state="pending")
    ticket, reply = files(tmp_path, ADD, ticket=t)
    before = snapshot(repo)
    assert run(repo, "submit", ticket, "--reply", reply) == cli.REFUSED
    assert "only approved tickets" in capsys.readouterr().out
    assert changed(before, repo) == set()


def test_a_ticket_failing_its_checks_waits_for_the_engineer_and_writes_nothing(repo, tmp_path, capsys):
    t = copy.deepcopy(request(ADD)[0])
    t.pop("change_sites")
    ticket, reply = files(tmp_path, ADD, ticket=t)
    before = snapshot(repo)
    assert run(repo, "submit", ticket, "--reply", reply) == cli.REVIEW
    assert "invalid_ticket" in capsys.readouterr().out
    assert changed(before, repo) == set()
    assert cli.load_record(repo, ADD)["status"] == "awaiting_review"


def test_a_reply_outside_the_ticket_scope_writes_nothing(repo, tmp_path, capsys):
    _, e = request(ADD)
    wide = copy.deepcopy(e)
    wide["rules"].append({**wide["rules"][0], "env_site": "stage-centralus", "sources": ["10.103.15.0/24"]})
    ticket, reply = files(tmp_path, ADD, reply=wide)
    before = snapshot(repo)
    assert run(repo, "submit", ticket, "--reply", reply) == cli.REFUSED
    assert "does not select" in capsys.readouterr().out
    assert changed(before, repo) == set()


def test_a_stop_reply_waits_for_review_and_writes_nothing(repo, tmp_path, capsys):
    ticket, reply = files(tmp_path, ADD, reply={"outcome": "stop_and_ask", "reason": "free_text_conflict", "rules": []})
    before = snapshot(repo)
    assert run(repo, "submit", ticket, "--reply", reply) == cli.REVIEW
    assert changed(before, repo) == set()
    assert cli.load_record(repo, ADD)["status"] == "awaiting_review"  # a stop waits for the engineer; never a rejection


def test_submitting_twice_is_refused(repo, tmp_path, capsys):
    ticket, reply = files(tmp_path, ADD)
    assert run(repo, "submit", ticket, "--reply", reply) == cli.DONE
    after_first = snapshot(repo)
    assert run(repo, "submit", ticket, "--reply", reply) == cli.REFUSED
    assert "already drafted" in capsys.readouterr().out
    assert changed(after_first, repo) == set()


@pytest.mark.parametrize("number", [ADD, REMOVE])
def test_reject_puts_every_byte_back_and_records_the_reason(repo, tmp_path, number):
    ticket, reply = files(tmp_path, number)
    before = snapshot(repo)
    run(repo, "submit", ticket, "--reply", reply)
    assert run(repo, "reject", number, "Requester withdrew it") == cli.DONE
    assert changed(before, repo) == set()
    record = cli.load_record(repo, number)
    assert record["status"] == "rejected" and record["history"][-1]["reason"] == "Requester withdrew it"
    assert run(repo, "submit", ticket, "--reply", reply) == cli.DONE  # a rejected ticket can start again


def test_reject_keeps_an_edit_made_before_the_draft(repo, tmp_path):
    """An uncommitted edit already in the file is part of 'before', so reject returns to it."""
    path = repo / ADD_FILE
    path.write_text(path.read_text() + "# an uncommitted edit by the engineer\n")
    ticket, reply = files(tmp_path, ADD)
    before = snapshot(repo)
    run(repo, "submit", ticket, "--reply", reply)
    run(repo, "reject", ADD, "wrong partner")
    assert changed(before, repo) == set()
    assert path.read_text().endswith("# an uncommitted edit by the engineer\n")


@pytest.mark.parametrize("command", [("reject", ADD, "why"), ("approve", ADD), ("fix", ADD, "note", "--reply", "R")])
def test_an_edit_after_the_draft_stops_the_command_and_survives(repo, tmp_path, capsys, command):
    ticket, reply = files(tmp_path, ADD)
    run(repo, "submit", ticket, "--reply", reply)
    path = repo / ADD_FILE
    path.write_text(path.read_text() + "# edited after the draft\n")
    after_edit = snapshot(repo)
    argv = [reply if a == "R" else a for a in command]
    assert run(repo, *argv) == cli.REFUSED
    assert "changed since the draft" in capsys.readouterr().out
    assert changed(after_edit, repo) == set()
    assert cli.load_record(repo, ADD)["status"] == "drafted"


def test_fix_replaces_the_draft_in_one_write(repo, tmp_path, capsys):
    _, e = request(ADD)
    ticket, reply = files(tmp_path, ADD)
    before = snapshot(repo)
    run(repo, "submit", ticket, "--reply", reply)
    fixed = copy.deepcopy(e)
    fixed["rules"][0]["name"] = "https-rprt-to-fourthcoffeeFiles"
    fixed_path = tmp_path / "fixed.json"
    fixed_path.write_text(json.dumps(fixed))
    assert run(repo, "fix", ADD, "Use the partner's service name", "--reply", str(fixed_path)) == cli.DONE
    text = (repo / ADD_FILE).read_text()
    assert "007-https-rprt-to-fourthcoffeeFiles" in text and "https-rprt-to-fourthcoffeeFs" not in text
    assert changed(before, repo) == {ADD_FILE}
    record = cli.load_record(repo, ADD)
    assert record["history"][-1]["note"] == "Use the partner's service name"
    assert run(repo, "reject", ADD, "still wrong") == cli.DONE  # after a fix, reject still returns to the start
    assert changed(before, repo) == set()


def test_a_fix_that_stops_is_refused(repo, tmp_path, capsys):
    ticket, reply = files(tmp_path, ADD)
    run(repo, "submit", ticket, "--reply", reply)
    after = snapshot(repo)
    stop = tmp_path / "stop.json"
    stop.write_text(json.dumps({"outcome": "stop_and_ask", "reason": "free_text_conflict", "rules": []}))
    assert run(repo, "fix", ADD, "note", "--reply", str(stop)) == cli.REFUSED
    assert changed(after, repo) == set()


def test_approve_marks_the_draft_and_ends_changes(repo, tmp_path, capsys):
    ticket, reply = files(tmp_path, ADD)
    run(repo, "submit", ticket, "--reply", reply)
    after = snapshot(repo)
    assert run(repo, "approve", ADD) == cli.DONE
    assert "stage 4" in capsys.readouterr().out
    assert cli.load_record(repo, ADD)["status"] == "approved"
    assert run(repo, "reject", ADD, "too late") == cli.REFUSED
    assert changed(after, repo) == set()


def test_a_command_with_no_draft_is_refused(repo, capsys):
    assert run(repo, "approve", "RITM0099999") == cli.REFUSED
    assert "no draft on record" in capsys.readouterr().out


def plant_backup(repo):
    """Leave a backup beside the lab primary sett file, as a failed write would."""
    backup = repo / Path(REMOVE_FILE).parent / f".sett.tfvars{BACKUP}k3j9x2"
    backup.write_bytes((repo / REMOVE_FILE).read_bytes())
    return backup


@pytest.mark.parametrize("command", ["submit", "fix", "reject", "approve"])
def test_every_command_refuses_while_a_recovery_backup_remains(repo, tmp_path, capsys, command):
    ticket, reply = files(tmp_path, ADD)
    if command != "submit":
        run(repo, "submit", ticket, "--reply", reply)
    backup = plant_backup(repo)
    before = snapshot(repo)
    argv = {"submit": ["submit", ticket, "--reply", reply], "fix": ["fix", ADD, "n", "--reply", reply],
            "reject": ["reject", ADD, "why"], "approve": ["approve", ADD]}[command]
    capsys.readouterr()
    assert run(repo, *argv) == cli.BACKUPS
    out = capsys.readouterr().out
    assert str(backup) in out and str(repo / REMOVE_FILE) in out
    assert changed(before, repo) == set()


def test_the_writer_itself_refuses_while_a_backup_remains(repo):
    """The check sits in apply_reply too, so a caller that skips the CLI is still stopped."""
    plant_backup(repo)
    t, e = request(ADD)
    before = snapshot(repo)
    with pytest.raises(BackupsRemainError):
        apply_reply(repo, t, e)
    assert changed(before, repo) == set()


def test_a_failed_undo_leaves_a_backup_and_the_next_command_is_refused(repo, tmp_path, capsys, monkeypatch):
    """End to end: a partial write exits 3 naming the backup, and the next submit is stopped by it."""
    import workflow.scope as scope
    real, calls = scope.os.replace, []

    def flaky(*args):
        calls.append(args)
        if len(calls) in (2, 3):  # 1 primary swapped, 2 DR fails, 3 undo of primary fails
            raise OSError(28, "No space left on device")
        return real(*args)

    t, e = request("RITM0011001")  # a draft at both sites of one environment
    assert len({r["env_site"] for r in e["rules"]}) >= 2
    ticket, reply = files(tmp_path, "RITM0011001")
    monkeypatch.setattr(scope.os, "replace", flaky)
    assert run(repo, "submit", ticket, "--reply", reply) == cli.BACKUPS
    assert BACKUP in capsys.readouterr().out
    monkeypatch.undo()
    monkeypatch.setenv("FWAGENT_STATE_DIR", str(tmp_path / "state"))
    t2, r2 = files(tmp_path, ADD)
    assert run(repo, "submit", t2, "--reply", r2) == cli.BACKUPS


def test_draft_records_live_outside_the_repo(monkeypatch):
    monkeypatch.delenv("FWAGENT_STATE_DIR", raising=False)
    where = cli.state_dir(REPO)
    assert REPO not in where.parents and Path.home() in where.parents
