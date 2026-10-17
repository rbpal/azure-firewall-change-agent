"""The rule insert, on the repo's real rules .tfvars files and the eval's labelled drafts. Every check here must be able to fail."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from workflow.rule_index import next_index
from workflow.tfvars_writer import DraftError, insert_rule, render_entry, rule_fields, write_rule

REPO = Path(__file__).resolve().parents[2]
SETT = "infra/envs/prod-eastus2/firewall_policy_rule_collection_groups/sett.tfvars"
XFER_DEV = "infra/envs/dev-eastus2/firewall_policy_rule_collection_groups/xfer.tfvars"
SETT_DEV = "infra/envs/dev-centralus/firewall_policy_rule_collection_groups/sett.tfvars"
TERRAFORM = shutil.which("terraform")

NETWORK = {"collection": "allow-sett-network-rules", "name": "https-sett-to-northwindFs",
           "sources": ["10.100.14.0/24"], "destinations": ["203.0.113.16/28"], "ports": ["443"], "protocol": "TCP"}
APP = {"collection": "allow-sett-app-rules", "name": "https-sett-to-contosoApi",
       "sources": ["ipg-sett-dev-dr"], "destinations": ["api.contoso.example"], "ports": ["443"], "protocol": "HTTPS"}
DNAT = {"collection": "allow-xfer-dnat-rules", "name": "sftp-wingtip-to-xferSftp", "sources": ["198.51.100.80/28"],
        "destinations": ["192.0.2.12"], "ports": ["2222"], "protocol": "TCP",
        "translated_address": "10.104.20.14", "translated_port": "22"}
CASES = [(SETT, "sett", NETWORK), (SETT_DEV, "sett", APP), (XFER_DEV, "xfer", DNAT)]


def insert(rel, spoke, draft):
    """Insert a draft into a real file's text at its next index; return (before, after)."""
    text = (REPO / rel).read_text()
    from workflow.tfvars_writer import rule_type
    return text, insert_rule(text, spoke, dict(draft), next_index(text, spoke, rule_type(draft)), rel)


def fmt(text):
    """Run terraform fmt on text and return what it would write."""
    return subprocess.run([TERRAFORM, "fmt", "-"], input=text, capture_output=True, text=True, check=True).stdout


@pytest.mark.parametrize("rel, spoke, draft", CASES, ids=["network", "application", "dnat"])
def test_the_insert_adds_one_entry_and_changes_nothing_else(rel, spoke, draft):
    """Removing the new entry's lines gives back the original file, byte for byte."""
    before, after = insert(rel, spoke, draft)
    entry = render_entry("x", rule_fields(draft))
    added = len(entry.splitlines())
    a, b = before.splitlines(keepends=True), after.splitlines(keepends=True)
    assert len(b) == len(a) + added
    start = next(i for i, (x, y) in enumerate(zip(a, b)) if x != y)
    assert b[:start] + b[start + added:] == a


@pytest.mark.skipif(TERRAFORM is None, reason="terraform not installed")
@pytest.mark.parametrize("rel, spoke, draft", CASES, ids=["network", "application", "dnat"])
def test_terraform_fmt_leaves_the_result_unchanged(rel, spoke, draft):
    """The entry is written in the exact layout terraform fmt produces."""
    _, after = insert(rel, spoke, draft)
    assert fmt(after) == after


def test_the_network_rule_goes_at_the_end_of_its_collection_with_the_next_key():
    """prod-eastus2 sett network rules end at 023, so the new rule is 024, after 023."""
    before, after = insert(SETT, "sett", NETWORK)
    assert next_index(before, "sett", "network") == "024"
    assert after.index('"023-') < after.index('"024-https-sett-to-northwindFs" = {')
    assert '''        "024-https-sett-to-northwindFs" = {
          name                  = "https-sett-to-northwindFs"
          protocols             = ["TCP"]
          source_addresses      = ["10.100.14.0/24"]
          destination_addresses = ["203.0.113.16/28"]
          destination_ports     = ["443"]
        }
''' in after


def test_application_and_dnat_fields_follow_the_repo_layout():
    """Application ports become Https:443; DNAT gets one destination_address and the translation."""
    assert rule_fields(APP)["protocols"] == ["Https:443"]
    assert rule_fields(APP)["destination_fqdns"] == ["api.contoso.example"]
    d = rule_fields(DNAT)
    assert (d["destination_address"], d["translated_address"], d["translated_port"]) == ("192.0.2.12", "10.104.20.14", "22")


@pytest.mark.parametrize("env_site, spoke, error", [
    ("prod-westus", "sett", "unknown env-site"),
    ("prod-eastus2", "zzzz", "not routed"),
    ("prod-eastus2", "../../../etc", "not routed"),
])
def test_an_unknown_env_site_or_spoke_is_refused(env_site, spoke, error):
    """The path is built only from env-sites and spokes in routing.yaml; nothing is written."""
    with pytest.raises(DraftError, match=error):
        write_rule(REPO, env_site, spoke, NETWORK)


@pytest.mark.parametrize("change, error", [
    ({"collection": "allow-sett-app-rules"}, "goes in allow-sett-network-rules"),
    ({"name": "024-https-sett-to-northwindFs"}, "STD-NAME-03"),
    ({"name": "Https Sett"}, "STD-NAME-03"),
    ({"sources": ['10.0.0.0/8"] }']}, "characters"),
    ({"destinations": ["${var.x}"]}, "characters"),
    ({"sources": ["10.100.14.1/24"]}, "not an address"),
    ({"sources": []}, "non-empty"),
    ({"protocol": "GRE"}, "not TCP"),
    ({"name": "amqps-sett-to-northwindMq"}, "already has a rule named"),
], ids=["wrong-collection", "index-in-name", "bad-name", "quote-breakout", "interpolation",
        "host-bits", "no-sources", "bad-protocol", "name-exists"])
def test_a_bad_draft_is_refused(change, error):
    """Each of these drafts stops the writer before any text changes."""
    with pytest.raises(DraftError, match=error):
        insert(SETT, "sett", {**NETWORK, **change})


def test_a_missing_collection_is_refused_for_now():
    """Creating a new collection is not built yet, so a draft for one stops with a clear message."""
    with pytest.raises(DraftError, match="not found"):
        insert(SETT, "sett", {**DNAT, "collection": "allow-sett-dnat-rules"})


def test_a_dnat_rule_needs_exactly_one_destination():
    """DNAT translates one public IP; two destinations are refused."""
    with pytest.raises(DraftError, match="exactly one destination"):
        insert(XFER_DEV, "xfer", {**DNAT, "destinations": ["192.0.2.12", "192.0.2.13"]})


def test_read_back_catches_a_rendered_value_that_differs(monkeypatch):
    """If the rendered entry ever disagrees with the draft, the insert stops."""
    import workflow.tfvars_writer as w
    real = w.render_entry
    monkeypatch.setattr(w, "render_entry", lambda key, fields: real(key, {**fields, "destination_ports": ["8443"]}))
    with pytest.raises(DraftError, match="read-back"):
        insert(SETT, "sett", NETWORK)


def test_read_back_catches_an_extra_change(monkeypatch):
    """If the insert ever adds more than the one rule, the insert stops."""
    import workflow.tfvars_writer as w
    real = w.render_entry
    monkeypatch.setattr(w, "render_entry",
                        lambda key, fields: real(key, fields) + real("099-extra-sett-to-x", {**fields, "name": "extra-sett-to-x"}))
    with pytest.raises(DraftError, match="other than"):
        insert(SETT, "sett", NETWORK)


def test_write_rule_writes_the_file_on_disk(tmp_path):
    """On a copy of the repo's data, write_rule changes only the one spoke file."""
    shutil.copytree(REPO / "data" / "network", tmp_path / "data" / "network")
    shutil.copytree(REPO / "infra" / "envs" / "prod-eastus2", tmp_path / "infra" / "envs" / "prod-eastus2")
    path, key = write_rule(tmp_path, "prod-eastus2", "sett", NETWORK)
    assert key == "024-https-sett-to-northwindFs"
    assert path == tmp_path / SETT
    assert '"024-https-sett-to-northwindFs"' in path.read_text()
    others = [p for p in (tmp_path / "infra").rglob("*.tfvars") if p != path]
    assert all(p.read_text() == (REPO / p.relative_to(tmp_path)).read_text() for p in others)


def _label_rules():
    """Every add rule in the validation labels whose collection already exists in its file."""
    out = []
    for p in sorted((REPO / "evals" / "requests" / "validation").glob("*.yaml")):
        e = yaml.safe_load(p.read_text())["expected"]
        if e["outcome"] != "draft" or e.get("action") == "remove":
            continue
        for r in e["rules"]:
            rel = f"infra/envs/{r['env_site']}/firewall_policy_rule_collection_groups/{r['spoke']}.tfvars"
            if f"    {r['collection']} = {{" in (REPO / rel).read_text():
                out.append(pytest.param(rel, r, id=f"{p.stem[-4:]}-{r['env_site']}"))
    return out


@pytest.mark.skipif(TERRAFORM is None, reason="terraform not installed")
@pytest.mark.parametrize("rel, rule", _label_rules())
def test_every_labelled_draft_inserts_cleanly(rel, rule):
    """The eval's own answer keys write into their real files, read back exactly and pass terraform fmt."""
    draft = {k: v for k, v in rule.items() if k not in ("env_site", "spoke")}
    _, after = insert(rel, rule["spoke"], draft)
    assert fmt(after) == after
