"""Tier 1 checks on plan JSON. The plan is built here from the repo's dev-eastus2 rules
files, shaped like `terraform show -json` but with no real IDs, so nothing private is
committed. Each test breaks one thing and expects exactly that finding."""

import copy
import json
from pathlib import Path

import pytest

from policy import tier1  # puts mcp/ on the path, so data_readers imports below
from data_readers.read_env_site_ipgroup import load_hcl  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
ENV = REPO / "infra" / "envs" / "dev-eastus2"
BLOCKS = {"nat_rule_collections": "nat_rule_collection", "network_rule_collections": "network_rule_collection",
          "application_rule_collections": "application_rule_collection"}


def _tfvars(path: Path, name: str) -> dict:
    """Load the one variable a tfvars file holds, with the same parser the tools use."""
    return load_hcl(path.read_text(), name, str(path))


def _rule(block: str, rv: dict) -> dict:
    """Shape one rule from the tfvars the way the module sends it to Azure."""
    ids = lambda names: [f"/ipGroups/{n}" for n in names]  # noqa: E731
    r = {"name": rv["name"], "source_addresses": rv.get("source_addresses", []),
         "source_ip_groups": ids(rv.get("source_ip_groups", []))}
    if block == "application_rule_collection":
        r["destination_fqdns"] = rv["destination_fqdns"]
        r["protocols"] = [{"type": p.split(":")[0], "port": int(p.split(":")[1])} for p in rv["protocols"]]
    elif block == "nat_rule_collection":
        r.update({k: rv[k] for k in ("protocols", "destination_address", "destination_ports",
                                    "translated_address", "translated_port")})
    else:
        r.update(protocols=rv["protocols"], destination_addresses=rv.get("destination_addresses", []),
                 destination_ip_groups=ids(rv.get("destination_ip_groups", [])),
                 destination_ports=rv["destination_ports"])
    return r


def build_plan() -> dict:
    """A plan for afwp-hub-dev-eastus2 built from its tfvars files."""
    variables, resources = {}, [{"type": "azurerm_firewall_policy", "values": {"name": "afwp-hub-dev-eastus2"}}]
    for name, g in _tfvars(ENV / "ip-groups.tfvars", "ip_groups").items():
        resources.append({"type": "azurerm_ip_group", "values": {"name": g["name"], "cidrs": g["cidrs"]}})
    for f in sorted((ENV / "firewall_policy_rule_collection_groups").glob("*.tfvars")):
        var = f.stem
        g = _tfvars(f, var)
        variables[var] = {"value": g}
        values = {"name": g["name"], "priority": g["priority"]}
        for key, block in BLOCKS.items():
            values[block] = [{"name": c["name"], "priority": c["priority"], "action": c["action"],
                              "rule": [_rule(block, rv) for _, rv in sorted(c["rules"].items())]}
                             for c in (g.get(key) or {}).values()]
        resources.append({"type": "azurerm_firewall_policy_rule_collection_group", "values": values})
    return {"variables": variables,
            "planned_values": {"root_module": {"child_modules": [{"resources": resources}]}}}


PLAN = build_plan()


@pytest.fixture
def plan():
    """A fresh copy of the dev-eastus2 plan for one test to break."""
    return copy.deepcopy(PLAN)


def group(plan, name):
    """The planned values of one rule collection group."""
    return next(r["values"] for r in plan["planned_values"]["root_module"]["child_modules"][0]["resources"]
                if r["type"] == "azurerm_firewall_policy_rule_collection_group" and r["values"]["name"] == name)


def dnat(plan):
    """The one DNAT rule in dev-eastus2 xfer."""
    return group(plan, "xfer")["nat_rule_collection"][0]["rule"][0]


def found(plan):
    """Findings as (level, standard) pairs."""
    return [(f.level, f.standard) for f in tier1.run(plan)]


# ------------------------------------------------------------ the real data

def test_dev_eastus2_has_only_the_two_wildcard_cautions(plan):
    lines = [f.line() for f in tier1.run(plan)]
    assert lines == [
        "caution STD-COLL-02 sett/allow-sett-app-rules/https-sett-to-cnnAll: wildcard FQDN *.cnn.com",
        "caution STD-COLL-02 sett/allow-sett-app-rules/https-sett-to-googleAll: wildcard FQDN *.google.com",
    ]


def test_model_reads_every_rule_with_its_key(plan):
    m = tier1.model(plan)
    rules = [r for g in m["groups"] for c in g["collections"] for r in c["rules"]]
    assert len(rules) == 61 and all(r["key"] for r in rules)
    assert m["policy"] == "afwp-hub-dev-eastus2" and "ipg-xfer-dev" in m["ip_groups"]


# ------------------------------------------------------------ STD-COLL-04 blocks

@pytest.mark.parametrize("source", ["0.0.0.0/0", "*", "Any"])
def test_open_dnat_blocks(plan, source):
    dnat(plan)["source_addresses"] = [source]
    assert found(plan)[0] == ("block", "STD-COLL-04")


def test_dnat_with_no_source_blocks(plan):
    dnat(plan)["source_addresses"] = []
    assert ("block", "STD-COLL-04") in found(plan)


def test_open_dnat_is_reported_once_not_also_as_a_wildcard(plan):
    dnat(plan)["source_addresses"] = ["0.0.0.0/0"]
    assert [s for _, s in found(plan)].count("STD-COLL-02") == 2  # only the two FQDN wildcards


def test_main_exits_2_on_a_block_and_0_otherwise(plan, tmp_path, capsys):
    ok = tmp_path / "ok.json"
    ok.write_text(json.dumps(plan))
    assert tier1.main(["tier1", str(ok)]) == 0
    dnat(plan)["source_addresses"] = ["*"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(plan))
    assert tier1.main(["tier1", str(bad)]) == 2
    assert "1 blocking" in capsys.readouterr().out


# ------------------------------------------------------------ STD-COLL-02 cautions

@pytest.mark.parametrize("field, value", [("source_addresses", "*"), ("destination_addresses", "0.0.0.0/0")])
def test_any_in_a_network_rule_is_a_caution(plan, field, value):
    group(plan, "ledg")["network_rule_collection"][0]["rule"][0][field] = [value]
    assert ("caution", "STD-COLL-02") in found(plan)
    assert ("block", "STD-COLL-04") not in found(plan)


def test_exact_fqdn_is_not_flagged(plan):
    lines = [f.line() for f in tier1.run(plan)]
    assert not any("www.google.com" in x or "www.cnn.com" in x for x in lines)


# ------------------------------------------------------------ STD-COLL-01

def test_group_priority_other_than_200(plan):
    group(plan, "hub")["priority"] = 300
    assert ("caution", "STD-COLL-01") in found(plan)


@pytest.mark.parametrize("change", [{"priority": 2500}, {"action": "Deny"}])
def test_collection_priority_or_action_wrong(plan, change):
    group(plan, "ledg")["network_rule_collection"][0].update(change)
    assert ("caution", "STD-COLL-01") in found(plan)


# ------------------------------------------------------------ STD-COLL-06

def test_dnat_destination_must_be_this_firewalls_public_ip(plan):
    dnat(plan)["destination_address"] = "192.0.2.10"  # prod-eastus2's public IP
    assert ("caution", "STD-COLL-06") in found(plan)


@pytest.mark.parametrize("address", ["10.100.20.14", "10.105.20.14", "not-an-ip"])
def test_dnat_must_translate_inside_this_site(plan, address):
    dnat(plan)["translated_address"] = address  # prod, dev DR, junk
    assert ("caution", "STD-COLL-06") in found(plan)


def test_public_port_used_twice(plan):
    c = group(plan, "xfer")["nat_rule_collection"][0]
    c["rule"].append({**c["rule"][0], "name": "sftp-litware-to-xferSftp"})
    assert ("caution", "STD-COLL-06") in found(plan)


def test_policy_missing_from_routing(plan):
    plan["planned_values"]["root_module"]["child_modules"][0]["resources"][0]["values"]["name"] = "afwp-unknown"
    assert ("caution", "STD-COLL-06") in found(plan)


# ------------------------------------------------------------ STD-NAME-01 to 05

def test_bad_group_name(plan):
    group(plan, "hub")["name"] = "Settlement"
    assert ("caution", "STD-NAME-01") in found(plan)


def test_collection_name_must_match_its_type(plan):
    group(plan, "ledg")["network_rule_collection"][0]["name"] = "allow-ledg-app-rules"
    assert ("caution", "STD-NAME-02") in found(plan)


def test_rule_key_must_follow_the_pattern(plan):
    plan["variables"]["ledg"]["value"]["network_rule_collections"]["allow-ledg-network-rules"]["rules"] = {
        ("1-" + k[4:] if i == 0 else k): v for i, (k, v) in enumerate(
            plan["variables"]["ledg"]["value"]["network_rule_collections"]["allow-ledg-network-rules"]["rules"].items())}
    assert ("caution", "STD-NAME-03") in found(plan)


def test_rule_indexes_must_run_without_gaps(plan):
    rules = plan["variables"]["ledg"]["value"]["network_rule_collections"]["allow-ledg-network-rules"]["rules"]
    last = sorted(rules)[-1]
    rules["099" + last[3:]] = rules.pop(last)
    assert ("caution", "STD-NAME-03") in found(plan)


def test_ticket_number_in_a_rule_name(plan):
    r = group(plan, "ledg")["network_rule_collection"][0]["rule"][0]
    rules = plan["variables"]["ledg"]["value"]["network_rule_collections"]["allow-ledg-network-rules"]["rules"]
    key = next(k for k, v in rules.items() if v["name"] == r["name"])
    rules[key]["name"] = r["name"] = r["name"] + "RITM0010042"
    assert ("caution", "STD-NAME-05") in found(plan)


def test_bad_ip_group_name(plan):
    plan["planned_values"]["root_module"]["child_modules"][0]["resources"].append(
        {"type": "azurerm_ip_group", "values": {"name": "sett-servers", "cidrs": ["10.104.14.0/24"]}})
    assert ("caution", "STD-NAME-04") in found(plan)


def test_blocks_come_first(plan):
    dnat(plan)["source_addresses"] = ["*"]
    group(plan, "hub")["priority"] = 300
    assert tier1.run(plan)[0].level == "block"
