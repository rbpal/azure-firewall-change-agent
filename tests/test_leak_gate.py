"""The leak gate. Each test runs it in a throwaway git repo with a fake block list.

The fake GUID and email are built from pieces, so this file never holds a
whole one and the gate does not block its own tests."""

import subprocess
import sys
from pathlib import Path

import pytest

GATE = Path(__file__).resolve().parent.parent / ".githooks" / "leak_gate.py"
FAKE_TERMS = "# fake block list for tests\nGlobex Corporation\n10.42.\nzqxw\n"
FAKE_GUID = "3f2b8c1e" + "-9a4d-4e6f-b7a1-2c3d4e5f6a7b"
FAKE_EMAIL = "someone" + "@globex.test"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    work = tmp_path / "work"
    work.mkdir()
    terms = tmp_path / "terms.txt"
    terms.write_text(FAKE_TERMS)
    monkeypatch.setenv("LEAK_GATE_TERMS", str(terms))
    run = lambda *a: subprocess.run(["git", *a], cwd=work, check=True, capture_output=True)
    run("init", "-q")
    run("config", "user.email", "test@example.com")
    run("config", "user.name", "Test")
    (work / "README.md").write_text("clean\n")
    run("add", ".")
    run("commit", "-q", "-m", "first")
    return work, terms, run


def gate(work, *args, stdin=""):
    return subprocess.run([sys.executable, str(GATE), *args], cwd=work, input=stdin,
                          capture_output=True, text=True)


def stage(work, run, name, text):
    (work / name).write_text(text)
    run("add", name)


@pytest.mark.parametrize("text", [
    "owner: Globex Corporation\n",
    "owner: GLOBEX CORPORATION\n",           # case does not matter
    "source = 10.42.7.0/24\n",               # an address prefix
    "rules = zqxw-network-rules\n",          # an app code on the list
    "id = " + FAKE_GUID + "\n",
    "contact: " + FAKE_EMAIL + "\n",
])
def test_real_data_is_blocked(repo, text):
    work, _, run = repo
    stage(work, run, "notes.md", text)
    result = gate(work, "--staged")
    assert result.returncode == 1
    assert "BLOCKED" in result.stderr


@pytest.mark.parametrize("text", [
    "owner: Contoso\n",
    "source = 10.100.14.0/24\n",
    "rules = zqxwx\n",                       # a whole-word term does not match inside another word
    "id = 00000000-0000-0000-0000-000000000000\n",
    "contact: someone@example.com\n",
])
def test_synthetic_data_passes(repo, text):
    work, _, run = repo
    stage(work, run, "notes.md", text)
    assert gate(work, "--staged").returncode == 0


def test_a_term_in_a_file_name_is_blocked(repo):
    work, _, run = repo
    stage(work, run, "zqxw.tfvars", "x = 1\n")
    assert gate(work, "--staged").returncode == 1


def test_gitignore_may_name_private_things_but_not_ids(repo):
    work, _, run = repo
    stage(work, run, ".gitignore", "zqxw-private/\n")
    assert gate(work, "--staged").returncode == 0
    stage(work, run, ".gitignore", "zqxw-private/\n# " + FAKE_GUID + "\n")
    assert gate(work, "--staged").returncode == 1


def test_the_hit_never_prints_the_term(repo):
    work, _, run = repo
    stage(work, run, "notes.md", "owner: Globex Corporation\n")
    result = gate(work, "--staged")
    assert "term #1" in result.stderr
    assert "Globex" not in result.stderr + result.stdout


def test_missing_block_list_fails_closed(repo, monkeypatch, tmp_path):
    work, _, _ = repo
    monkeypatch.setenv("LEAK_GATE_TERMS", str(tmp_path / "nope.txt"))
    assert gate(work, "--staged").returncode != 0


def test_empty_block_list_fails_closed(repo):
    work, terms, _ = repo
    terms.write_text("# only comments\n\n")
    assert gate(work, "--staged").returncode != 0


def test_push_catches_a_commit_made_with_no_verify(repo):
    work, _, run = repo
    stage(work, run, "notes.md", "owner: Globex Corporation\n")
    run("commit", "-q", "--no-verify", "-m", "sneaky")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=work, capture_output=True, text=True).stdout.strip()
    first = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=work, capture_output=True, text=True).stdout.strip()
    stdin = f"refs/heads/main {head} refs/heads/main {first}\n"
    assert gate(work, "--push", stdin=stdin).returncode == 1


def test_push_catches_a_term_in_the_commit_message(repo):
    work, _, run = repo
    stage(work, run, "notes.md", "clean\n")
    run("commit", "-q", "--no-verify", "-m", "Copy rules from Globex Corporation")
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=work, capture_output=True, text=True).stdout.strip()
    first = subprocess.run(["git", "rev-parse", "HEAD~1"], cwd=work, capture_output=True, text=True).stdout.strip()
    assert gate(work, "--push", stdin=f"refs/heads/main {head} refs/heads/main {first}\n").returncode == 1
