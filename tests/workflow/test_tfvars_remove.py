"""Removing a rule and renumbering its collection, on a fixture and on the repo's real files. Every check here must be able to fail."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from workflow.rule_index import collection_indexes
from workflow.tfvars_writer import DraftError, parse_rules, remove_rule, write_removal

REPO = Path(__file__).resolve().parents[2]
TERRAFORM = shutil.which("terraform")


def entry(key, port, kind="network"):
    """One rule entry; each rule gets its own port so a moved field would show."""
    if kind == "app":
        return f'''        "{key}" = {{
          name              = "{key[4:]}"
          protocols         = ["Https:443"]
          source_addresses  = ["10.105.20.0/24"]
          destination_fqdns = ["api{port}.contoso.example"]
        }}
'''
    return f'''        "{key}" = {{
          name                  = "{key[4:]}"
          protocols             = ["TCP"]
          source_addresses      = ["10.105.20.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["{port}"]
        }}
'''


def block(wrapper, name, priority, rules):
    """One collections block holding the given entries."""
    return f'''  {wrapper} = {{
    {name} = {{
      name     = "{name}"
      priority = {priority}
      action   = "Allow"
      rules = {{
{"".join(rules)}      }}
    }}
  }}
'''


def fixture(n=50):
    """A xfer.tfvars with network rules 001..n and application rules 001-009."""
    network = [entry(f"{i:03d}-sftp-xfer-to-partner{i}", 1000 + i) for i in range(1, n + 1)]
    app = [entry(f"{i:03d}-https-xfer-to-api{i}", i, "app") for i in range(1, 10)]
    return ('xfer = {\n  name                = "xfer"\n  firewall_policy_key = "firewall_policy"\n  priority            = 200\n\n'
            + block("network_rule_collections", "allow-xfer-network-rules", 2000, network) + "\n"
            + block("application_rule_collections", "allow-xfer-app-rules", 3000, app) + "}\n")


def draft_for(i):
    """The removal request for fixture network rule i."""
    return {"collection": "allow-xfer-network-rules", "name": f"sftp-xfer-to-partner{i}", "sources": ["10.105.20.0/24"],
            "destinations": ["198.51.100.32/28"], "ports": [str(1000 + i)], "protocol": "TCP"}


def network(text):
    """The network collection's rules as (key, name, port), in file order."""
    group = parse_rules(text, "xfer", "fixture")
    rules = next(c["rules"] for c in group["collections"] if c["name"] == "allow-xfer-network-rules")
    return [(r["key"], r["name"], r["destination_ports"]) for r in rules]


def test_removing_003_of_50_leaves_001_to_049_in_the_same_order():
    """Every later rule moves down one number; names, order and fields are unchanged."""
    before = network(fixture())
    after_text, key = remove_rule(fixture(), "xfer", draft_for(3), "fixture")
    after = network(after_text)
    assert key == "003-sftp-xfer-to-partner3"
    assert [k[:3] for k, _, _ in after] == [f"{i:03d}" for i in range(1, 50)]
    kept = [r for r in before if r[0] != key]
    assert [(n, p) for _, n, p in after] == [(n, p) for _, n, p in kept]


def test_removing_the_last_rule_changes_no_other_key():
    """Removing 050 deletes only its own lines."""
    text = fixture()
    after_text, _ = remove_rule(text, "xfer", draft_for(50), "fixture")
    assert after_text == text.replace(entry("050-sftp-xfer-to-partner50", 1050), "")


def test_removing_two_rules_closes_both_gaps():
    """Remove 003, then the rule that was 010 (now 009): the collection runs 001-048."""
    once, _ = remove_rule(fixture(), "xfer", draft_for(3), "fixture")
    twice, key = remove_rule(once, "xfer", draft_for(10), "fixture")
    assert key == "009-sftp-xfer-to-partner10"
    assert collection_indexes(twice, "xfer", "network") == list(range(1, 49))
    assert [n for _, n, _ in network(twice)] == [f"sftp-xfer-to-partner{i}" for i in range(1, 51) if i not in (3, 10)]


def test_renumbering_goes_by_number_not_by_position():
    """In a file listed 001, 003, 002, 004, removing 003 leaves 002 alone and moves 004 to 003."""
    keys = ["001-sftp-xfer-to-partner1", "003-sftp-xfer-to-partner3", "002-sftp-xfer-to-partner2", "004-sftp-xfer-to-partner4"]
    rules = [entry(k, 1000 + int(k[:3])) for k in keys]
    text = ('xfer = {\n  name                = "xfer"\n  firewall_policy_key = "firewall_policy"\n  priority            = 200\n\n'
            + block("network_rule_collections", "allow-xfer-network-rules", 2000, rules) + "}\n")
    after_text, _ = remove_rule(text, "xfer", draft_for(3), "fixture")
    assert [k for k, _, _ in network(after_text)] == ["001-sftp-xfer-to-partner1", "002-sftp-xfer-to-partner2",
                                                     "003-sftp-xfer-to-partner4"]


def test_other_collections_keep_their_keys():
    """The application collection is untouched by a network removal."""
    after_text, _ = remove_rule(fixture(), "xfer", draft_for(3), "fixture")
    app = lambda t: t[t.index("  application_rule_collections"):]
    assert app(after_text) == app(fixture())


@pytest.mark.skipif(TERRAFORM is None, reason="terraform not installed")
def test_terraform_fmt_leaves_the_result_unchanged():
    """Renumbered keys keep their width, so the layout stays the one terraform fmt writes."""
    after_text, _ = remove_rule(fixture(), "xfer", draft_for(3), "fixture")
    out = subprocess.run([TERRAFORM, "fmt", "-"], input=after_text, capture_output=True, text=True, check=True).stdout
    assert out == after_text


@pytest.mark.parametrize("change, error", [
    ({"name": "sftp-xfer-to-nobody"}, "has no rule named"),
    ({"ports": ["9999"]}, "field for field"),
    ({"sources": ["10.105.21.0/24"]}, "field for field"),
    ({"collection": "allow-xfer-app-rules"}, "is in allow-xfer-network-rules"),
], ids=["no-such-name", "wrong-port", "wrong-source", "wrong-collection"])
def test_a_removal_that_does_not_match_exactly_is_refused(change, error):
    """Only the exact labelled rule may be removed; anything else stops the writer."""
    with pytest.raises(DraftError, match=error):
        remove_rule(fixture(), "xfer", {**draft_for(3), **change}, "fixture")


def test_the_removal_check_catches_a_wrong_renumber(monkeypatch):
    """If renumbering ever skipped a rule, the read-back check stops the removal."""
    import workflow.tfvars_writer as w
    real = w.parse_rules
    calls = []

    def broken(text, spoke, path):
        """Parse normally, but on the read-back give one rule a wrong number."""
        group = real(text, spoke, path)
        calls.append(1)
        if len(calls) == 2:
            rules = next(c["rules"] for c in group["collections"] if c["name"] == "allow-xfer-network-rules")
            rules[5]["key"] = "999" + rules[5]["key"][3:]
        return group
    monkeypatch.setattr(w, "parse_rules", broken)
    with pytest.raises(DraftError, match="changed something other"):
        remove_rule(fixture(), "xfer", draft_for(3), "fixture")


def _own_rule(rel, spoke, collection, index):
    """Build a removal request from a real file's own rule at that index."""
    group = parse_rules((REPO / rel).read_text(), spoke, rel)
    rule = next(c for c in group["collections"] if c["name"] == collection)["rules"][index - 1]
    draft = {"collection": collection, "name": rule["name"], "protocol": rule["protocols"][0],
             "sources": rule.get("source_addresses", []) + rule.get("source_ip_groups", []),
             "destinations": rule.get("destination_addresses", []) + rule.get("destination_ip_groups", [])
             + rule.get("destination_fqdns", []),
             "ports": rule["destination_ports"]}
    return draft


def test_a_dr_file_ends_with_the_same_keys_as_its_primary():
    """Removing rule 003 from prod sett in both regions leaves the two collections with identical keys."""
    keys = []
    for site in ("prod-eastus2", "prod-centralus"):
        rel = f"infra/envs/{site}/firewall_policy_rule_collection_groups/sett.tfvars"
        draft = _own_rule(rel, "sett", "allow-sett-network-rules", 3)
        after_text, _ = remove_rule((REPO / rel).read_text(), "sett", draft, rel)
        group = parse_rules(after_text, "sett", rel)
        keys.append([r["key"] for c in group["collections"] for r in c["rules"]])
    assert keys[0] == keys[1]


def _removal_labels():
    """Every removal rule in the validation labels."""
    out = []
    for p in sorted((REPO / "evals" / "requests" / "validation").glob("*.yaml")):
        e = yaml.safe_load(p.read_text())["expected"]
        if e.get("action") == "remove":
            for r in e["rules"]:
                out.append(pytest.param(r, id=f"{p.stem[-4:]}-{r['env_site']}"))
    return out


@pytest.mark.parametrize("rule", _removal_labels())
def test_every_labelled_removal_applies_to_its_real_file(rule, tmp_path):
    """The eval's removal answers each match exactly one real rule, and the file stays valid."""
    shutil.copytree(REPO / "data" / "network", tmp_path / "data" / "network")
    shutil.copytree(REPO / "infra" / "envs" / rule["env_site"], tmp_path / "infra" / "envs" / rule["env_site"])
    draft = {k: v for k, v in rule.items() if k not in ("env_site", "spoke")}
    path, key = write_removal(tmp_path, rule["env_site"], rule["spoke"], draft)
    assert key.endswith(rule["name"])
    rule_type = "application" if rule["protocol"].upper() in ("HTTP", "HTTPS") else "network"
    numbers = collection_indexes(path.read_text(), rule["spoke"], rule_type, str(path))
    assert numbers == list(range(1, len(numbers) + 1))
