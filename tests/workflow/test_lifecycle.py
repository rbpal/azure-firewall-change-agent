"""One unfinished ticket per engineer; finishing and abandoning tickets. Every check must be able to fail.

GitHub is a fake that answers like gh does; git is real, in temporary repos. No test reaches GitHub.
"""

import json
import shutil
import subprocess
from pathlib import Path

import pytest

import workflow.cli as cli
import workflow.lifecycle as lc
from tests.workflow.test_mainline import commit_all, git, world  # noqa: F401  (world is a fixture)

REAL_WHOAMI = lc.whoami  # captured before the autouse fixture replaces it
REPO_NAME = "rbpal/azure-firewall-change-agent"
NUMBER, OTHER = "RITM0013002", "RITM0013003"
BRANCH = f"agent/{NUMBER}-3899dc4"
TICKET = {"number": NUMBER, "environments": ["dev"], "protocol": "TCP", "ports": ["443"], "partner": "Adventure Works",
          "sources": [{"environment": "dev", "site": "primary", "cidr": "10.104.14.0/24"}],
          "destination": [{"cidr": "198.51.100.64/28"}]}


class FakeGH:
    """Answers gh like GitHub would: pull requests by head branch, and records every call."""

    def __init__(self, prs=None, login="rbpal"):
        self.prs, self.login, self.calls = dict(prs or {}), login, []

    def __call__(self, *args):
        self.calls.append(args)
        if args[:2] == ("api", "user"):
            if isinstance(self.login, Exception):
                raise self.login
            return self.login + "\n"
        if args[:2] == ("pr", "list"):
            found = self.prs.get(args[args.index("--head") + 1])
            if isinstance(found, Exception):
                raise found
            return json.dumps([found] if found else [])
        if args[:2] == ("pr", "close"):
            return ""
        raise AssertionError(f"unexpected gh call {args}")


def pr(state="OPEN", oid=None, number=7, branch=BRANCH):
    """A pull request as gh pr list --json returns it."""
    return {"number": number, "url": f"https://github.com/{REPO_NAME}/pull/{number}", "state": state,
            "baseRefName": "main", "headRefName": branch, "mergeCommit": {"oid": oid} if oid else None,
            "mergedAt": "2026-11-03T20:00:00Z" if state == "MERGED" else None, "title": f"{NUMBER} | dev | sett 443",
            "body": "Adds TCP 443 from sett to Adventure Works at both dev sites."}


def record(status="approved"):
    """A workflow record with an acceptance and one drafted rule."""
    return {"number": NUMBER, "ticket": TICKET, "status": status, "reply": {"outcome": "draft"},
            "review": {"decision": "accept", "engineer": "rbpal"}, "files": {},
            "keys": [{"file": "infra/envs/dev-eastus2/x.tfvars", "key": "021-https-sett-to-adventureworksFs"}],
            "history": [{"action": "submit"}]}


@pytest.fixture
def place(tmp_path):
    """A state folder with the ticket's record, and demo-style folders holding its other files."""
    state = tmp_path / "state"
    state.mkdir()
    (state / f"{NUMBER}.json").write_text(json.dumps(record(), indent=2))
    folders = {name: tmp_path / name for name in ("01-waiting", "02-submit", "03-pr-description")}
    for f in folders.values():
        f.mkdir()
    (folders["02-submit"] / f"{NUMBER}.yaml").write_text("number: RITM0013002\n")
    (folders["02-submit"] / f"{NUMBER}.json").write_text('{"request": true}\n')  # same name as the record
    (folders["02-submit"] / f"{NUMBER}.status.json").write_text('{"foundry_status": "succeeded"}\n')
    (folders["03-pr-description"] / f"pr-description-{NUMBER}.md").write_text("# PR description\n")
    (folders["02-submit"] / f"{OTHER}.yaml").write_text("another ticket\n")
    sources = {"records": state, **folders}
    return state, sources, tmp_path / "04-archive", tmp_path / "05-pr-abandoned"


# ------------------------------------------------------------ who the engineer is, and which repository


def test_the_engineer_is_the_github_account_gh_is_signed_in_to():
    assert REAL_WHOAMI(FakeGH(login="rbpal")) == "rbpal"


def test_an_unreadable_identity_stops_with_a_clear_message():
    with pytest.raises(lc.Unverified, match="cannot tell who you are.*gh auth login"):
        REAL_WHOAMI(FakeGH(login=lc.Unverified("gh api failed: not logged in")))


@pytest.mark.parametrize("url", ["https://github.com/rbpal/azure-firewall-change-agent.git",
                                 "ssh://github.com/rbpal/azure-firewall-change-agent.git",
                                 "https://github.com/rbpal/azure-firewall-change-agent"])
def test_the_repository_is_its_github_owner_and_name(tmp_path, url):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    git(tmp_path, "remote", "add", "origin", url)
    assert lc.repo_id(tmp_path) == REPO_NAME


# ------------------------------------------------------------ the check before a new draft


def test_a_second_ticket_is_blocked_and_the_first_is_named_with_its_branch_pr_and_options(tmp_path):
    lc.register(tmp_path, NUMBER, "rbpal", REPO_NAME, branch=BRANCH)
    with pytest.raises(lc.Blocked) as stopped:
        lc.check_no_unfinished(tmp_path, "rbpal", REPO_NAME, OTHER, gh=FakeGH({BRANCH: pr("OPEN")}))
    text = str(stopped.value)
    for part in (NUMBER, BRANCH, f"https://github.com/{REPO_NAME}/pull/7 (open)", f"fwagent draft {NUMBER}",
                 f"fwagent finish {NUMBER}", f"fwagent abandon {NUMBER} --reason", f"before starting {OTHER}"):
        assert part in text


def test_a_merged_pr_is_pointed_out_but_the_ticket_still_blocks_until_finished(tmp_path):
    lc.register(tmp_path, NUMBER, "rbpal", REPO_NAME, branch=BRANCH)
    with pytest.raises(lc.Blocked, match="its pull request is merged"):
        lc.check_no_unfinished(tmp_path, "rbpal", REPO_NAME, OTHER, gh=FakeGH({BRANCH: pr("MERGED", "a" * 40)}))


def test_an_unreachable_github_still_blocks_and_says_the_pr_was_not_checked(tmp_path):
    lc.register(tmp_path, NUMBER, "rbpal", REPO_NAME, branch=BRANCH)
    with pytest.raises(lc.Blocked, match="Pull request: could not be checked"):
        lc.check_no_unfinished(tmp_path, "rbpal", REPO_NAME, OTHER, gh=FakeGH({BRANCH: lc.Unverified("offline")}))


@pytest.mark.parametrize("owner, repo, number", [("rbpal", REPO_NAME, NUMBER),  # the same ticket may go on
                                                 ("someone-else", REPO_NAME, OTHER),  # other engineers carry on
                                                 ("rbpal", "rbpal/another-repo", OTHER)])  # other repositories too
def test_only_the_same_engineer_in_the_same_repository_is_blocked(tmp_path, owner, repo, number):
    lc.register(tmp_path, NUMBER, "rbpal", REPO_NAME, branch=BRANCH)
    lc.check_no_unfinished(tmp_path, owner, repo, number, gh=FakeGH())


def test_fwagent_accept_stops_a_second_ticket_and_a_failed_run_does_not_abandon_the_first(
        tmp_path, monkeypatch, capsys, offline_main):
    from tests.workflow.test_agent import REQUESTS, foundry
    import yaml
    repo = tmp_path / "repo"
    shutil.copytree(cli.REPO / "data" / "network", repo / "data" / "network")
    shutil.copytree(cli.REPO / "infra" / "envs", repo / "infra" / "envs")
    monkeypatch.setenv("FWAGENT_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("FWAGENT_PROJECT_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")
    monkeypatch.setattr(cli, "live_agent", lambda *_: foundry("not json"))  # every run fails

    def submit_and_accept(number):
        data = yaml.safe_load((REQUESTS / "validation" / f"validation_{number}.yaml").read_text())
        path = tmp_path / f"{number}.yaml"
        path.write_text(yaml.safe_dump(data["ticket"]))
        cli.main(["submit", str(path)], repo=repo)
        version = cli.load_record(repo, number)["ticket_version"][:12]
        return cli.main(["accept", number, "--ticket-version", version, "--engineer", "rbpal", "--reason", "ok"], repo=repo)

    assert submit_and_accept("RITM0011001") == cli.REFUSED  # the run failed
    assert [e["number"] for e in lc.entries(tmp_path / "state")] == ["RITM0011001"]  # still unfinished
    capsys.readouterr()
    assert submit_and_accept("RITM0011002") == cli.REFUSED
    out = capsys.readouterr().out
    assert "already has an unfinished ticket" in out and "Ticket: RITM0011001" in out
    assert cli.load_record(repo, "RITM0011002")["status"] == "awaiting_review"  # never accepted, never drafted


# ------------------------------------------------------------ folder names


def test_the_folder_is_the_full_ticket_number_and_a_short_description_under_20_characters():
    name = lc.folder_name(NUMBER, lc.default_label(record(), None))
    assert name == "RITM0013002-sett443" and len(name) == 19
    assert lc.folder_name(NUMBER, "adventureworks443") == "RITM0013002-adventu" and len("RITM0013002-adventu") < 20


def test_without_a_drafted_rule_the_description_is_protocol_and_port():
    assert lc.default_label({"keys": []}, TICKET) == "tcp443"


@pytest.mark.parametrize("number, label", [("RITM13002", "sett443"), ("RITM0013002", "!!!")])
def test_a_folder_name_that_breaks_the_pattern_is_refused(number, label):
    with pytest.raises(lc.Blocked):
        lc.folder_name(number, label)


# ------------------------------------------------------------ the move: no overwrite, resumable


def test_files_are_copied_checked_and_only_then_removed_with_their_names_kept(place):
    state, sources, archive, _ = place
    manifest = lc.move_artifacts(lc.artifacts(NUMBER, sources), archive / "RITM0013002-sett443", {"note.txt": "x\n"})
    dest = archive / "RITM0013002-sett443"
    assert (dest / "records" / f"{NUMBER}.json").exists() and (dest / "02-submit" / f"{NUMBER}.json").exists()
    assert (dest / "03-pr-description" / f"pr-description-{NUMBER}.md").read_text() == "# PR description\n"
    assert manifest["originals_removed"] is True and not (state / f"{NUMBER}.json").exists()
    assert (sources["02-submit"] / f"{OTHER}.yaml").exists()  # another ticket's file is never touched


def test_an_existing_folder_not_made_by_the_workflow_is_never_overwritten(place):
    _, sources, archive, _ = place
    (archive / "RITM0013002-sett443").mkdir(parents=True)
    with pytest.raises(lc.Blocked, match="nothing was overwritten"):
        lc.move_artifacts(lc.artifacts(NUMBER, sources), archive / "RITM0013002-sett443", {})
    assert (sources["records"] / f"{NUMBER}.json").exists()


def test_a_move_interrupted_while_copying_resumes_and_loses_nothing(place, monkeypatch):
    _, sources, archive, _ = place
    files, real, copied = lc.artifacts(NUMBER, sources), shutil.copy2, []

    def crash_on_third(src, dst):
        copied.append(src)
        if len(copied) == 3:
            raise KeyboardInterrupt
        return real(src, dst)
    monkeypatch.setattr(lc.shutil, "copy2", crash_on_third)
    with pytest.raises(KeyboardInterrupt):
        lc.move_artifacts(files, archive / "RITM0013002-sett443", {})
    assert not (archive / "RITM0013002-sett443").exists() and all(p.exists() for _, p in files)
    monkeypatch.setattr(lc.shutil, "copy2", real)
    assert lc.move_artifacts(files, archive / "RITM0013002-sett443", {})["originals_removed"] is True
    assert not any(p.exists() for _, p in files)


def test_a_move_interrupted_after_the_folder_appeared_finishes_from_its_manifest(place, monkeypatch):
    _, sources, archive, _ = place
    files, real = lc.artifacts(NUMBER, sources), Path.unlink
    monkeypatch.setattr(Path, "unlink", lambda self, *a, **k: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        lc.move_artifacts(files, archive / "RITM0013002-sett443", {})
    monkeypatch.setattr(Path, "unlink", real)
    assert (archive / "RITM0013002-sett443" / lc.MANIFEST).exists() and all(p.exists() for _, p in files)
    assert lc.move_artifacts([], archive / "RITM0013002-sett443", {})["originals_removed"] is True
    assert not any(p.exists() for _, p in files)


def test_a_file_changed_after_it_was_copied_is_kept_not_deleted(place, monkeypatch):
    _, sources, archive, _ = place
    status = sources["02-submit"] / f"{NUMBER}.status.json"
    real = Path.unlink

    def change_then_unlink(self, *a, **k):
        if self.parent == sources["records"]:  # the first original removed
            status.write_text('{"changed": true}\n')  # someone edits a later file before its turn
        return real(self, *a, **k)
    monkeypatch.setattr(Path, "unlink", change_then_unlink)
    manifest = lc.move_artifacts(lc.artifacts(NUMBER, sources), archive / "RITM0013002-sett443", {})
    assert manifest["originals_removed"] is False and manifest["originals_kept"] == [str(status)]
    assert status.read_text() == '{"changed": true}\n'


# ------------------------------------------------------------ finish: merged into main, confirmed on GitHub


def merged_branch(world):
    """Push a ticket branch with one commit and merge it into origin main; return (branch tip, merge commit)."""
    repo = world.engineer
    git(repo, "checkout", "-q", "-b", BRANCH)
    (repo / "infra/envs/dev-eastus2/ip-groups.tfvars").write_text("# the drafted rule\n")
    tip = commit_all(repo, "RITM0013002: add the rule")
    git(repo, "push", "-q", "origin", BRANCH)
    git(repo, "checkout", "-q", "main")
    git(world.pusher, "fetch", "-q", "origin", BRANCH)
    git(world.pusher, "-c", "user.name=t", "-c", "user.email=t@example.com", "merge", "-q", "--no-ff",
        f"origin/{BRANCH}", "-m", "Merge pull request #7")
    git(world.pusher, "push", "-q", "origin", "main")
    return tip, git(world.pusher, "rev-parse", "HEAD").strip()


def finish(world, place, gh, owner="rbpal"):
    """Run finish for the ticket with the place's folders."""
    state, sources, archive, _ = place
    return lc.finish(world.engineer, state, NUMBER, owner, archive, sources,
                     json.loads((state / f"{NUMBER}.json").read_text()), gh=gh)


def test_finish_archives_a_merged_ticket_and_records_merged_apart_from_applied(world, place):
    state, sources, archive, _ = place
    _, merge = merged_branch(world)
    lc.register(state, NUMBER, "rbpal", REPO_NAME, branch=BRANCH, base=world.first)
    out = finish(world, place, FakeGH({BRANCH: pr("MERGED", merge)}))
    dest = archive / "RITM0013002-sett443"
    resolution = json.loads((dest / lc.RESOLUTION).read_text())
    assert resolution["outcome"] == "merged" and resolution["merge_commit"] == merge
    assert resolution["merged_into_main"] is True and resolution["applied_in_azure"].startswith("not recorded")
    assert resolution["pr_url"].endswith("/pull/7") and "10.104.14.0/24 to 198.51.100.64/28" in resolution["summary"]
    assert "Adds TCP 443" in (dest / "pull-request.md").read_text()
    assert json.loads((dest / "records" / f"{NUMBER}.json").read_text())["status"] == "merged"
    assert lc.entry(state, NUMBER) is None and "separate release step" in out
    assert git(world.engineer, "branch", "--list", BRANCH) == ""  # fully merged and clean: removed
    lc.check_no_unfinished(state, "rbpal", REPO_NAME, OTHER, gh=FakeGH())  # the next ticket may start


@pytest.mark.parametrize("answer, why", [
    (pr("OPEN"), "is open into main, not merged"),
    (None, "has no pull request"),
    (lc.Unverified("gh pr failed: offline"), "offline"),
    (pr("MERGED", "f" * 40), "merge commit is not on origin/main"),
])
def test_finish_moves_nothing_unless_github_and_main_confirm_the_merge(world, place, answer, why):
    state, sources, archive, _ = place
    merged_branch(world)
    lc.register(state, NUMBER, "rbpal", REPO_NAME, branch=BRANCH, base=world.first)
    with pytest.raises((lc.Blocked, lc.Unverified), match=why):
        finish(world, place, FakeGH({BRANCH: answer}))
    assert not archive.exists() and lc.entry(state, NUMBER) is not None
    assert json.loads((state / f"{NUMBER}.json").read_text())["status"] == "approved"


def test_only_the_owner_can_finish_or_abandon_a_ticket(world, place):
    state, sources, _, abandoned = place
    lc.register(state, NUMBER, "rbpal", REPO_NAME, branch=BRANCH)
    with pytest.raises(lc.Blocked, match="belongs to rbpal"):
        finish(world, place, FakeGH(), owner="someone-else")
    with pytest.raises(lc.Blocked, match="belongs to rbpal"):
        lc.abandon(world.engineer, state, NUMBER, "someone-else", "x", abandoned, sources, None, gh=FakeGH())


# ------------------------------------------------------------ abandon: explicit, closes the PR, voids the draft


def abandon(world, place, gh, **options):
    """Run abandon for the ticket with the place's folders."""
    state, sources, _, abandoned = place
    return lc.abandon(world.engineer, state, NUMBER, "rbpal", options.pop("reason", "Requester withdrew it"),
                      abandoned, sources, json.loads((state / f"{NUMBER}.json").read_text()), gh=gh, **options)


def test_abandon_closes_the_pr_voids_the_draft_and_approval_and_moves_the_files(world, place):
    state, sources, _, abandoned = place
    lc.register(state, NUMBER, "rbpal", REPO_NAME, branch=BRANCH)
    gh = FakeGH({BRANCH: pr("OPEN")})
    out = abandon(world, place, gh)
    assert ("pr", "close", "7", "--repo", REPO_NAME, "--comment", "Abandoned: Requester withdrew it") in gh.calls
    dest = abandoned / "RITM0013002-sett443"
    saved = json.loads((dest / "records" / f"{NUMBER}.json").read_text())
    assert saved["status"] == "abandoned" and saved["draft_valid"] is False and saved["reply"] is None
    assert "review" not in saved and saved["invalidated"]["approved"] is True
    assert saved["invalidated"]["review"]["engineer"] == "rbpal"
    resolution = json.loads((dest / lc.RESOLUTION).read_text())
    assert (resolution["reason"], resolution["engineer"], resolution["pr_closed"]) == ("Requester withdrew it", "rbpal", True)
    assert resolution["pr_url"].endswith("/pull/7") and resolution["at"]
    assert lc.entry(state, NUMBER) is None and "pull request was closed" in out


def test_an_abandoned_draft_cannot_be_approved_later(world, place, monkeypatch):
    state, *_ = place
    lc.register(state, NUMBER, "rbpal", REPO_NAME)
    abandon(world, place, FakeGH())
    monkeypatch.setenv("FWAGENT_STATE_DIR", str(state))
    with pytest.raises(cli.Refused, match="no draft on record"):
        cli.approve(world.engineer, NUMBER)


def test_abandon_needs_a_reason_and_refuses_a_merged_ticket(world, place):
    state, *_ = place
    lc.register(state, NUMBER, "rbpal", REPO_NAME, branch=BRANCH)
    with pytest.raises(lc.Blocked, match="needs a reason"):
        abandon(world, place, FakeGH(), reason="  ")
    with pytest.raises(lc.Blocked, match="already merged; run fwagent finish"):
        abandon(world, place, FakeGH({BRANCH: pr("MERGED", "a" * 40)}))


def test_abandon_stops_when_the_pr_status_cannot_be_read(world, place):
    state, sources, _, abandoned = place
    lc.register(state, NUMBER, "rbpal", REPO_NAME, branch=BRANCH)
    gh = FakeGH({BRANCH: lc.Unverified("gh pr failed: offline")})
    with pytest.raises(lc.Unverified, match="offline"):
        abandon(world, place, gh)
    assert not abandoned.exists() and lc.entry(state, NUMBER) is not None
    assert not [c for c in gh.calls if c[:2] == ("pr", "close")]


@pytest.fixture
def worked_branch(world, place):
    """A ticket branch in its own worktree, with an engineer's uncommitted edit."""
    state, *_ = place
    path = world.tmp / "wt"
    git(world.engineer, "worktree", "add", "-q", "-b", BRANCH, str(path), world.first)
    (path / "notes.txt").write_text("engineer's notes\n")
    lc.register(state, NUMBER, "rbpal", REPO_NAME, branch=BRANCH, worktree=str(path), base=world.first)
    return path


@pytest.mark.parametrize("typed", ["", "agent/wrong-name", None])
def test_a_branch_holding_work_is_kept_unless_its_name_is_typed(world, place, worked_branch, typed):
    out = abandon(world, place, FakeGH(), remove_branch=True, confirm=lambda prompt: typed)
    assert (worked_branch / "notes.txt").read_text() == "engineer's notes\n" and f"Branch {BRANCH} was kept" in out
    assert git(world.engineer, "branch", "--list", BRANCH) != ""


def test_typing_the_branch_name_deletes_the_branch_and_its_worktree(world, place, worked_branch):
    asked = []
    abandon(world, place, FakeGH(), remove_branch=True, confirm=lambda prompt: asked.append(prompt) or BRANCH)
    assert "holds work" in asked[0] and "notes.txt" in asked[0]
    assert not worked_branch.exists() and git(world.engineer, "branch", "--list", BRANCH) == ""


def test_without_remove_branch_nothing_is_asked_and_the_branch_stays(world, place, worked_branch):
    abandon(world, place, FakeGH(), confirm=lambda prompt: pytest.fail("must not ask"))
    assert worked_branch.exists() and git(world.engineer, "branch", "--list", BRANCH) != ""


def test_a_clean_branch_is_removed_without_asking(world, place):
    state, *_ = place
    path = world.tmp / "wt"
    git(world.engineer, "worktree", "add", "-q", "-b", BRANCH, str(path), world.first)
    lc.register(state, NUMBER, "rbpal", REPO_NAME, branch=BRANCH, worktree=str(path), base=world.first)
    abandon(world, place, FakeGH(), remove_branch=True, confirm=lambda prompt: pytest.fail("must not ask"))
    assert not path.exists() and git(world.engineer, "branch", "--list", BRANCH) == ""


def test_fwagent_abandon_and_active_use_the_configured_folders(world, place, monkeypatch, capsys):
    state, sources, _, abandoned = place
    monkeypatch.setenv("FWAGENT_STATE_DIR", str(state))
    monkeypatch.setenv("FWAGENT_ABANDONED_DIR", str(abandoned))
    monkeypatch.setenv("FWAGENT_ARTIFACT_DIRS", ":".join(str(sources[k]) for k in ("01-waiting", "02-submit",
                                                                                   "03-pr-description")))
    monkeypatch.setattr(lc, "whoami", lambda gh=None: "rbpal")
    lc.register(state, NUMBER, "rbpal", REPO_NAME)
    assert cli.main(["active"], repo=world.engineer) == cli.DONE and NUMBER in capsys.readouterr().out
    assert cli.main(["abandon", NUMBER, "--reason", "Duplicate of RITM0013001"], repo=world.engineer) == cli.DONE
    dest = abandoned / "RITM0013002-sett443"
    assert sorted(p.name for p in dest.iterdir()) == ["02-submit", "03-pr-description", lc.MANIFEST, "records",
                                                     lc.RESOLUTION]
    assert cli.main(["active"], repo=world.engineer) == cli.DONE and "No unfinished tickets" in capsys.readouterr().out
