"""The next-index function, on a three-collection fixture and on every real rules file. Every check here must be able to fail."""

import re
from pathlib import Path

import pytest

from workflow.rule_index import RuleIndexError, collection_indexes, collection_name, next_index

REPO = Path(__file__).resolve().parents[2]
RULE_FILES = sorted(REPO.glob("infra/envs/*/firewall_policy_rule_collection_groups/*.tfvars"))


def rule(key, kind):
    """One rule entry as tfvars text; DNAT rules carry the translation fields."""
    name = key[4:]
    if kind == "dnat":
        return f'''        "{key}" = {{
          name                = "{name}"
          protocols           = ["TCP"]
          source_addresses    = ["203.0.113.48/28"]
          destination_address = "192.0.2.15"
          destination_ports   = ["2221"]
          translated_address  = "10.105.20.14"
          translated_port     = "22"
        }}
'''
    if kind == "app":
        return f'''        "{key}" = {{
          name              = "{name}"
          source_addresses  = ["10.105.20.0/24"]
          destination_fqdns = ["api.contoso.example"]
          protocols         = [{{ type = "Https", port = 443 }}]
        }}
'''
    return f'''        "{key}" = {{
          name                  = "{name}"
          protocols             = ["TCP"]
          source_addresses      = ["10.105.20.0/24"]
          destination_addresses = ["198.51.100.32/28"]
          destination_ports     = ["22"]
        }}
'''


def collection(block, name, priority, action, keys, kind):
    """One collection block holding the given keys."""
    body = "".join(rule(k, kind) for k in keys)
    return f'''  {block} = {{
    {name} = {{
      name     = "{name}"
      priority = {priority}
      action   = "{action}"
      rules = {{
{body}      }}
    }}
  }}
'''


def spoke_file(dnat=2, network=6, app=9, network_keys=None):
    """A xfer.tfvars with DNAT, network and application collections of the given sizes."""
    keys = lambda n, svc: [f"{i:03d}-{svc}-xfer-to-partner{i}" for i in range(1, n + 1)]
    parts = ['xfer = {\n  name                = "xfer"\n  firewall_policy_key = "firewall_policy"\n  priority            = 200\n']
    if dnat:
        parts.append(collection("nat_rule_collections", "allow-xfer-dnat-rules", 1000, "Dnat", keys(dnat, "sftp"), "dnat"))
    if network or network_keys:
        parts.append(collection("network_rule_collections", "allow-xfer-network-rules", 2000, "Allow",
                                network_keys or keys(network, "sftp"), "network"))
    if app:
        parts.append(collection("application_rule_collections", "allow-xfer-app-rules", 3000, "Allow", keys(app, "https"), "app"))
    return "".join(parts) + "}\n"


FIXTURE = spoke_file()


def whole_file_next_index(text):
    """The wrong way: highest "NNN- key anywhere in the file, plus one."""
    highest = max(int(n) for n in re.findall(r'"(\d{3})-', text))
    return f"{highest + 1:03d}"


def test_a_new_network_rule_gets_the_next_network_number():
    """Network runs 001-006, so the next network rule is 007, not 003 (DNAT) or 010 (app)."""
    assert next_index(FIXTURE, "xfer", "network") == "007"


def test_a_new_dnat_rule_gets_the_next_dnat_number():
    """DNAT runs 001-002, so the next DNAT rule is 003."""
    assert next_index(FIXTURE, "xfer", "dnat") == "003"


def test_a_new_application_rule_gets_the_next_application_number():
    """Application runs 001-009, so the next application rule is 010."""
    assert next_index(FIXTURE, "xfer", "application") == "010"


def test_a_whole_file_search_gets_the_fixture_wrong():
    """The fixture tells the two methods apart: a whole-file search answers 010 for a network rule."""
    assert whole_file_next_index(FIXTURE) == "010"
    assert whole_file_next_index(FIXTURE) != next_index(FIXTURE, "xfer", "network")


def test_a_missing_collection_starts_at_001():
    """A spoke with no DNAT collection yet gets 001; code creates the collection with the rule."""
    assert next_index(spoke_file(dnat=0), "xfer", "dnat") == "001"


@pytest.mark.parametrize("keys", [
    ["001-sftp-xfer-to-a", "002-sftp-xfer-to-b", "004-sftp-xfer-to-c"],
    ["002-sftp-xfer-to-a", "003-sftp-xfer-to-b"],
    ["001-sftp-xfer-to-a", "001-sftp-xfer-to-b"],
], ids=["gap-at-003", "no-001", "duplicate-001"])
def test_numbers_that_break_the_standard_stop_the_function(keys):
    """A gap, a missing 001 or a repeated number stops it; it never guesses."""
    with pytest.raises(RuleIndexError, match="no gap"):
        next_index(spoke_file(network_keys=keys), "xfer", "network")


def test_a_key_without_an_index_stops_the_function():
    """A key that does not start with three digits stops it."""
    with pytest.raises(RuleIndexError, match="three-digit index"):
        next_index(spoke_file(network_keys=["001-sftp-xfer-to-a", "sftp-xfer-to-b"]), "xfer", "network")


def test_an_unknown_rule_type_is_refused():
    """Only dnat, network and application exist."""
    with pytest.raises(RuleIndexError, match="unknown rule type"):
        next_index(FIXTURE, "xfer", "nat")


def test_collection_names_follow_std_name_02():
    """Application rules live in an -app- collection, not -application-."""
    assert [collection_name("sett", t) for t in ("dnat", "network", "application")] == [
        "allow-sett-dnat-rules", "allow-sett-network-rules", "allow-sett-app-rules"]


def test_the_collection_is_full_at_999():
    """Three digits allow 999 rules; the 1000th is refused."""
    with pytest.raises(RuleIndexError, match="999"):
        next_index(spoke_file(dnat=0, app=0, network=999), "xfer", "network")


@pytest.mark.parametrize("path", RULE_FILES, ids=lambda p: f"{p.parts[-3]}/{p.stem}")
def test_every_real_collection_runs_from_001_with_no_gap(path):
    """The repo's own rules files obey STD-NAME-03, so the function works on them."""
    text, spoke = path.read_text(), path.stem
    for rule_type in ("dnat", "network", "application"):
        numbers = collection_indexes(text, spoke, rule_type, str(path))
        assert next_index(text, spoke, rule_type, str(path)) == f"{len(numbers) + 1:03d}"
