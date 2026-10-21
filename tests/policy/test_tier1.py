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
    assert len(rules) == 62 and all(r["key"] for r in rules)  # 62 since the 2026-10-21 drift rule in rprt
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


@pytest.mark.parametrize("key, ok", [
    ("005-https-onpremPrimary-to-portFs", True),
    ("001-https-sett-to-northwindFs", True),
    ("001-https-Onprem-to-portFs", False),
    ("001-https-on_prem-to-portFs", False),
])
def test_rule_key_allows_a_lower_camel_case_source(key, ok):
    """STD-NAME-03 names on-prem sources like onpremPrimary; a capital first letter or an underscore still fails."""
    assert bool(tier1.RULE_KEY.match(key)) is ok


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


# ------------------------------------------------------------ plans that change rules

LEDG = "allow-ledg-network-rules"


def changing(plan, name):
    """Add a resource_changes entry for one group: before is today's rules, after is the planned values."""
    after = group(plan, name)
    plan.setdefault("resource_changes", []).append({
        "type": "azurerm_firewall_policy_rule_collection_group",
        "change": {"before": copy.deepcopy(after), "after": after}})
    return plan["resource_changes"][-1]["change"]


def ledg_rules(plan):
    """The planned rules and the tfvars rules of the ledg network collection."""
    return (group(plan, "ledg")["network_rule_collection"][0]["rule"],
            plan["variables"]["ledg"]["value"]["network_rule_collections"][LEDG]["rules"])


def add_rule(plan, name, fields):
    """Add a new rule at the end of ledg's network collection, in both the plan and the tfvars."""
    planned, tfvars = ledg_rules(plan)
    key = f"{len(tfvars) + 1:03d}-{name}"
    tfvars[key] = {"name": name, **fields}
    planned.append(_rule("network_rule_collection", tfvars[key]))
    return key


def lines(plan, standard):
    """The finding lines for one standard."""
    return [f.line() for f in tier1.run(plan) if f.standard == standard]


COPY_OF_001 = {"protocols": ["TCP"], "source_addresses": ["10.104.16.0/24"],
               "destination_addresses": ["203.0.113.64/28"], "destination_ports": ["443"]}


def test_a_plan_with_no_changes_has_no_change_findings(plan):
    changing(plan, "ledg")
    assert not lines(plan, "STD-COLL-07") and not lines(plan, "STD-COLL-08")


# ------------------------------------------------------------ STD-COLL-07

def test_new_rule_that_duplicates_an_existing_one(plan):
    changing(plan, "ledg")
    add_rule(plan, "https-ledg-to-litwareFsCopy", COPY_OF_001)
    [line] = lines(plan, "STD-COLL-07")
    assert "https-ledg-to-litwareFsCopy: duplicate by 001-https-ledg-to-litwareFs" in line
    assert line.endswith("ledg.tfvars")


def test_new_rule_covered_by_a_wider_rule(plan):
    changing(plan, "ledg")
    add_rule(plan, "https-ledg-to-litwareHost", {**COPY_OF_001, "destination_addresses": ["203.0.113.65"]})
    [line] = lines(plan, "STD-COLL-07")
    assert "covers by 001-https-ledg-to-litwareFs" in line


def test_new_rule_with_new_traffic_is_not_flagged(plan):
    changing(plan, "ledg")
    add_rule(plan, "https-ledg-to-newPartner", {**COPY_OF_001, "destination_addresses": ["198.51.100.200/32"]})
    assert not lines(plan, "STD-COLL-07")


def test_a_new_rule_already_in_the_files_does_not_match_itself(plan):
    change = changing(plan, "ledg")
    change["before"]["network_rule_collection"][0]["rule"].pop()  # the last rule is new in this plan
    assert not lines(plan, "STD-COLL-07") and not lines(plan, "STD-COLL-08")


def test_existing_duplicates_are_not_reported_when_nothing_is_added(plan):
    add_rule(plan, "https-ledg-to-litwareFsCopy", COPY_OF_001)  # in the plan, but no resource_changes
    assert not lines(plan, "STD-COLL-07")


def test_a_duplicate_already_in_before_is_not_new(plan):
    add_rule(plan, "https-ledg-to-litwareFsCopy", COPY_OF_001)
    changing(plan, "ledg")  # before and after both hold the copy, so this plan adds nothing
    assert not lines(plan, "STD-COLL-07")


def test_new_rule_missing_from_tfvars_is_a_caution_not_a_crash(plan):
    changing(plan, "ledg")
    planned, _ = ledg_rules(plan)
    planned.append({**planned[0], "name": "https-ledg-to-ghost"})
    assert any("not in the tfvars" in x for x in lines(plan, "STD-COLL-07"))


def test_new_rule_the_tool_refuses_is_a_caution_not_a_crash(plan):
    changing(plan, "ledg")
    add_rule(plan, "https-ledg-to-badGroup", {**COPY_OF_001, "source_addresses": [], "source_ip_groups": ["ipg-nope-dev"]})
    assert any("not checked" in x for x in lines(plan, "STD-COLL-07"))


# ------------------------------------------------------------ STD-COLL-08

def test_removing_a_rule_is_allowed(plan):
    change = changing(plan, "ledg")
    change["after"] = copy.deepcopy(change["after"])
    change["after"]["network_rule_collection"][0]["rule"].pop(1)
    assert not lines(plan, "STD-COLL-08")


def test_changing_an_existing_rule(plan):
    changing(plan, "ledg")
    planned, _ = ledg_rules(plan)
    planned[0]["destination_ports"] = ["8443"]
    [line] = lines(plan, "STD-COLL-08")
    assert line.endswith(f"ledg/{LEDG}/{planned[0]['name']}: an existing rule was changed")


def test_description_change_is_not_a_rule_change(plan):
    changing(plan, "ledg")
    ledg_rules(plan)[0][0]["description"] = "new words"
    assert not lines(plan, "STD-COLL-08")


def test_reordering_rules(plan):
    changing(plan, "ledg")
    planned, _ = ledg_rules(plan)
    planned[0], planned[1] = planned[1], planned[0]
    assert any("reordered" in x for x in lines(plan, "STD-COLL-08"))


def test_new_rule_not_at_the_end(plan):
    changing(plan, "ledg")
    add_rule(plan, "https-ledg-to-newPartner", {**COPY_OF_001, "destination_addresses": ["198.51.100.200/32"]})
    planned, _ = ledg_rules(plan)
    planned.insert(0, planned.pop())
    assert any("reordered" in x for x in lines(plan, "STD-COLL-08"))


def test_new_rule_at_the_end_is_fine(plan):
    changing(plan, "ledg")
    add_rule(plan, "https-ledg-to-newPartner", {**COPY_OF_001, "destination_addresses": ["198.51.100.200/32"]})
    assert not lines(plan, "STD-COLL-08")


# ------------------------------------------------------------ service tags

@pytest.mark.parametrize("address", ["Storage", "Storage.EastUS2", "AzureCloud.eastus2",
                                     "10.104.16.5", "10.104.16.5-10.104.16.9", "203.0.113.64/28", "*"])
def test_valid_addresses_and_tags_pass(plan, address):
    ledg_rules(plan)[0][0]["destination_addresses"] = [address]
    assert not lines(plan, "SERVICE-TAG")


def test_unknown_service_tag(plan):
    ledg_rules(plan)[0][0]["destination_addresses"] = ["StorageAccounts"]
    [line] = lines(plan, "SERVICE-TAG")
    assert line.endswith("StorageAccounts is not an Azure service tag")


def test_service_tag_for_another_region(plan):
    ledg_rules(plan)[0][0]["destination_addresses"] = ["Storage.WestEurope"]
    [line] = lines(plan, "SERVICE-TAG")
    assert "this policy is in eastus2" in line


def test_tag_on_the_source_side_is_checked_too(plan):
    ledg_rules(plan)[0][0]["source_addresses"] = ["Sql.CentralUS"]
    assert lines(plan, "SERVICE-TAG")


def test_service_tag_list_has_no_comments_or_blanks():
    assert "Storage" in tier1.SERVICE_TAGS and len(tier1.SERVICE_TAGS) > 1000
    assert not any(t.startswith("#") or not t for t in tier1.SERVICE_TAGS)
