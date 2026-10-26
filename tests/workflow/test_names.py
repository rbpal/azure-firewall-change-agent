"""URL and hostname typos: each is returned to the engineer with a plain explanation and never corrected.

Before 2026-10-25 a trailing line break passed (the schema's `$` matches before a final newline, and
a YAML `|` block adds one), and every other typo came back as a raw regular expression. Each check
here must be able to fail.
"""

import copy
import json

import pytest

import workflow.cli as cli
from workflow.intake import intake_findings
from workflow.scope import ApprovalError, plan_writes
from workflow.urls import hostname_problems, url_problems
from tests.workflow.test_cli import REPO, changed, repo, request, run, snapshot  # noqa: F401  (repo is a fixture)

NUMBER = "RITM0011015"


def ticket_with(kind, value):
    """RITM0011015 with one destination of this kind and value."""
    t = copy.deepcopy(request(NUMBER)[0])
    t["destination"] = [{kind: value}]
    return t


BAD = [
    ("url", "https://api.litware .example/v1/upload", "a space at character 20"),
    ("url", "https://api.litware.example/v1/up load", "a space at character 34"),
    ("url", "https://api.litware.example/v1\t/upload", "a tab at character 31"),
    ("url", "https://api.litware.example\n/v1/upload", "a line break at character 28"),
    ("url", "https://api.litware.example/v1/upload\n", "a line break at character 38"),  # passed before
    ("url", "https://api.litware.example/v1/upload\r\n", "a line break at character 38"),
    ("url", " https://api.litware.example/v1/upload", "a space at character 1"),
    ("url", "https://api.litware.example/v1/upload ", "a space at character 38"),
    ("url", "https://api.litware.example/v1 x", "an invisible character U+00A0"),
    ("url", "https://api.lit​ware.example/v1", "an invisible character U+200B"),
    ("url", "https://api.lıtware.example/v1", "a non-ASCII character 'ı' (U+0131)"),
    ("url", "api.litware.example/v1/upload", "it has no scheme"),
    ("url", "https:/api.litware.example/v1", "it has no scheme"),
    ("url", "ftp://api.litware.example/v1", "the scheme is 'ftp'; only http and https are allowed"),
    ("url", "https://api..litware.example/v1", "it has two dots in a row"),
    ("url", "https://.api.litware.example/v1", "it starts with a dot"),
    ("url", "https://api.litware.example./v1", "it ends with a dot"),
    ("url", "https://api_litware.example/v1", "the character '_' is not allowed in a hostname"),
    ("url", "https://-api.litware.example/v1", "the label '-api' starts or ends with a hyphen"),
    ("url", "https://api.litware.example:0/v1", "the port '0' is not a number from 1 to 65535"),
    ("url", "https://api.litware.example:70000/v1", "the port '70000' is not a number from 1 to 65535"),
    ("url", "https://api.litware.example:44a/v1", "the port '44a' is not a number from 1 to 65535"),
    ("url", "https://user@api.litware.example/v1", "a user name or password before the hostname"),
    ("url", "https://api/v1", "it has no domain"),
    ("url", "https://api.litware.e1/v1", "the last label 'e1' must be 2 to 63 letters"),
    ("fqdn", "api.litware .example", "a space at character 12"),
    ("fqdn", "api.litware\t.example", "a tab at character 12"),
    ("fqdn", "api.litware.example\n", "a line break at character 20"),  # passed before
    ("fqdn", "api.litware.example ", "a space at character 20"),
    ("fqdn", "api..litware.example", "it has two dots in a row"),
    ("fqdn", "api.litware.example.", "it ends with a dot"),
    ("fqdn", "API.litware.example", "it has upper-case letters"),
    ("fqdn", "https://api.litware.example", "it looks like a URL"),
    ("fqdn", "api_litware.example", "the character '_' is not allowed"),
    ("fqdn", "api.lit​ware.example", "an invisible character U+200B"),
    ("fqdn", "litware", "it has no domain"),
]


@pytest.mark.parametrize("kind, value, says", BAD, ids=[repr(v) for _, v, _ in BAD])
def test_a_typo_is_returned_with_a_plain_reason_and_no_raw_pattern(kind, value, says):
    findings = intake_findings(REPO, ticket_with(kind, value))
    code = "invalid_url" if kind == "url" else "invalid_hostname"
    assert [f["code"] for f in findings] == [code]  # one finding: no raw schema error, no url_port_conflict
    f = findings[0]
    assert f["where"] == f"destination/0/{kind}" and not f["acceptable"]
    assert says in f["message"] and "The workflow will not correct it" in f["message"]
    assert "does not match" not in f["message"]


@pytest.mark.parametrize("kind, value", [
    ("url", "https://api.litware.example/v1/upload"),
    ("url", "https://api.litware.example:8443/v1/upload?x=1#top"),
    ("url", "http://api.litware.example"),
    ("url", "https://API.Litware.example/v1"),  # the schema allows upper case in a URL; DNS ignores case
    ("fqdn", "api.litware.example"),
    ("fqdn", "*.northwind.example"),  # a wildcard: a caution, not a typo (STD-COLL-02)
    ("fqdn", "*"),
])
def test_a_valid_url_or_hostname_has_no_finding(kind, value):
    assert (url_problems if kind == "url" else hostname_problems)(value) == []
    t = ticket_with(kind, value)
    if kind == "url" and value.startswith("http://"):
        t["protocol"] = "HTTP"
    if ":8443" in value:
        t["ports"] = ["8443"]
    assert [f for f in intake_findings(REPO, t) if f["code"] in ("invalid_url", "invalid_hostname", "invalid_ticket")] == []


def test_every_validation_ticket_still_passes_the_name_checks():
    import yaml
    for path in sorted((REPO / "evals" / "requests" / "validation").glob("*.yaml")):
        t = yaml.safe_load(path.read_text())["ticket"]
        assert not [f for f in intake_findings(REPO, t) if f["code"] in ("invalid_url", "invalid_hostname")], path.name


def test_a_hostname_over_253_characters_is_left_to_the_dns_tool():
    # RITM0011063: the DNS tool refuses it and the agent stops with dns_lookup_failed (evals/README.md).
    import yaml
    t = yaml.safe_load((REPO / "evals" / "requests" / "validation" / "validation_RITM0011063.yaml").read_text())["ticket"]
    assert len(t["destination"][0]["url"]) > 253 and intake_findings(REPO, t) == []


def test_a_typo_waits_for_an_edit_is_never_corrected_and_never_reaches_the_agent(repo, tmp_path, monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(cli, "read_reply", lambda path: calls.append(path) or {"outcome": "draft", "rules": []})
    value = "https://api.litware.example/v1/upload\n"
    ticket = tmp_path / "t.json"
    ticket.write_text(json.dumps(ticket_with("url", value)))
    before = snapshot(repo)
    assert run(repo, "submit", str(ticket)) == cli.REVIEW
    assert "[invalid_url, needs an edit] destination/0/url" in capsys.readouterr().out
    record = cli.load_record(repo, NUMBER)
    assert record["ticket"]["destination"][0]["url"] == value  # kept exactly, line break and all
    assert run(repo, "accept", NUMBER, "--ticket-version", record["ticket_version"][:12], "--engineer", "E",
               "--reason", "r", "--reply", "unused.json") == cli.REFUSED
    assert calls == [] and changed(before, repo) == set()


def test_a_draft_write_refuses_a_ticket_whose_url_has_a_typo(repo):
    with pytest.raises(ApprovalError, match="invalid_url"):
        plan_writes(repo, ticket_with("url", "https://api.litware.example/v1/upload\n"), copy.deepcopy(request(NUMBER)[1]))
