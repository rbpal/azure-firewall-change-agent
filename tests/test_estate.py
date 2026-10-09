"""The estate generator. Every check here must be able to fail."""

import ipaddress
import re
import shutil
import subprocess
import sys
from pathlib import Path

import hcl2
import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "data"))
import generate_estate as ge  # noqa: E402

POLICIES = ge.build_estate()
KEY = re.compile(r"^(\d{3})-([a-z]+)-([a-z]+)-to-([a-z][a-zA-Z]+)$")
KINDS = ("dnat", "network", "app")
INTERNAL = [ipaddress.ip_network("10.100.0.0/14"), ipaddress.ip_network("10.104.0.0/14")]
DOC = [ipaddress.ip_network(n) for n in ("192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]


@pytest.fixture(scope="module")
def out(tmp_path_factory):
    root = tmp_path_factory.mktemp("estate")
    ge.write_estate(root)
    return root


def unquote(v):
    """python-hcl2 keeps the quote marks; strip them from strings and keys."""
    if isinstance(v, dict):
        return {unquote(k): unquote(x) for k, x in v.items()}
    if isinstance(v, list):
        return [unquote(x) for x in v]
    if isinstance(v, str) and len(v) >= 2 and v[0] == v[-1] == '"':
        return v[1:-1]
    return v


def rules(group):
    return [r for kind in KINDS for r in group[kind]]


def addresses(rule):
    for field in ("source_addresses", "destination_addresses"):
        yield from rule.get(field, [])
    for field in ("destination_address", "translated_address"):
        if field in rule:
            yield rule[field]


# ------------------------------------------------------------ files


def test_two_runs_are_identical(out, tmp_path):
    ge.write_estate(tmp_path)
    first = {p.relative_to(out): p.read_bytes() for p in out.rglob("*") if p.is_file()}
    second = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*") if p.is_file()}
    assert first == second


def test_file_count(out):
    # 8 policies x 6 groups, less the three DR spokes that are not built, plus 8 IP group files
    tfvars = list((out / "infra").rglob("*.tfvars"))
    assert len(tfvars) == 8 * 6 - len(ge.NO_DR) + 8


@pytest.mark.skipif(shutil.which("terraform") is None, reason="terraform not installed")
def test_terraform_fmt_leaves_files_unchanged(out):
    result = subprocess.run(["terraform", "fmt", "-check", "-recursive", str(out / "infra")],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stdout


def test_files_parse_and_match_the_model(out):
    for name, policy in POLICIES.items():
        for spoke, group in policy["groups"].items():
            path = out / "infra" / "envs" / name / "firewall_policy_rule_collection_groups" / f"{spoke}.tfvars"
            parsed = unquote(hcl2.load(path.open()))[spoke]
            for kind, attr in [("dnat", "nat_rule_collections"), ("network", "network_rule_collections"),
                               ("app", "application_rule_collections")]:
                if not group[kind]:
                    assert attr not in parsed, f"{path}: empty {attr} should be left out"
                    continue
                [collection] = parsed[attr].values()
                assert [r["name"] for r in collection["rules"].values()] == [r["name"] for r in group[kind]]


# ------------------------------------------------------------ the clean pattern


def test_every_policy_holds_40_to_60_rules():
    for name, policy in POLICIES.items():
        count = sum(len(rules(g)) for g in policy["groups"].values())
        assert 40 <= count <= 60, f"{name}: {count} rules"


def test_priorities_and_collection_names_are_fixed(out):
    expected = {"nat_rule_collections": (1000, "dnat", "Dnat"), "network_rule_collections": (2000, "network", "Allow"),
                "application_rule_collections": (3000, "app", "Allow")}
    for path in (out / "infra").rglob("firewall_policy_rule_collection_groups/*.tfvars"):
        spoke = path.stem
        group = unquote(hcl2.load(path.open()))[spoke]
        assert group["name"] == spoke and group["priority"] == 200
        for attr, (priority, word, action) in expected.items():
            for cname, c in group.get(attr, {}).items():
                assert cname == c["name"] == f"allow-{spoke}-{word}-rules"
                assert c["priority"] == priority and c["action"] == action, path


def test_rule_keys_follow_the_naming_standard(out):
    for path in (out / "infra").rglob("firewall_policy_rule_collection_groups/*.tfvars"):
        group = unquote(hcl2.load(path.open()))[path.stem]
        for attr in ("nat_rule_collections", "network_rule_collections", "application_rule_collections"):
            for c in group.get(attr, {}).values():
                keys = list(c["rules"])
                assert [int(KEY.match(k).group(1)) for k in keys] == list(range(1, len(keys) + 1)), path
                for key, rule in c["rules"].items():
                    assert rule["name"] == key[4:], key
                    assert ge.SERVICES.get(KEY.match(key).group(2)), key


def test_no_deny_rules(out):
    for path in (out / "infra").rglob("*.tfvars"):
        assert '"Deny"' not in path.read_text(), path


# ------------------------------------------------------------ addresses


def test_every_address_is_synthetic():
    for policy in POLICIES.values():
        for group in policy["groups"].values():
            for rule in rules(group):
                for a in addresses(rule):
                    net = ipaddress.ip_network(a, strict=True)
                    assert any(net.subnet_of(r) for r in INTERNAL + DOC), a


def test_internal_addresses_belong_to_their_own_env_site(out):
    plan = yaml.safe_load((out / "data" / "estate" / "address-plan.yaml").read_text())["ranges"]
    for name, policy in POLICIES.items():
        es = policy["env_site"]
        mine = [ipaddress.ip_network(r["cidr"]) for r in plan
                if r["environment"] == es["environment"] and r["site"] == es["site"] and r["kind"] != "env-site"]
        for group in policy["groups"].values():
            for rule in rules(group):
                for a in addresses(rule):
                    net = ipaddress.ip_network(a)
                    if any(net.subnet_of(r) for r in INTERNAL):
                        assert any(net.subnet_of(m) for m in mine), f"{name}: {a}"


def test_ip_groups_used_by_rules_exist(out):
    for name, policy in POLICIES.items():
        defined = unquote(hcl2.load((out / "infra" / "envs" / name / "ip-groups.tfvars").open()))["ip_groups"]
        for group in policy["groups"].values():
            for rule in rules(group):
                for g in rule.get("source_ip_groups", []):
                    assert g in defined, f"{name}: {g}"


def test_dnat_is_prod_primary_only_and_never_open():
    for name, policy in POLICIES.items():
        dnat = [r for g in policy["groups"].values() for r in g["dnat"]]
        assert bool(dnat) == (name == "prod-eastus2"), name
        for rule in dnat:
            assert rule["source_addresses"] not in (["0.0.0.0/0"], ["*"])
            assert ipaddress.ip_address(rule["translated_address"]) in ipaddress.ip_network("10.100.20.0/24")
            assert rule["destination_address"] == policy["env_site"]["public_ip"]


# ------------------------------------------------------------ primary and DR


def test_dr_spokes_missing_exactly_where_planned():
    for policy in POLICIES.values():
        es = policy["env_site"]
        for spoke in ge.SPOKES:
            expected = es["site"] == "primary" or (es["environment"], spoke) not in ge.NO_DR
            assert (spoke in policy["groups"]) == expected, (es["name"], spoke)


def test_dr_mirrors_primary():
    for env in ge.ENVS:
        primary, dr = POLICIES[f"{env}-eastus2"]["groups"], POLICIES[f"{env}-centralus"]["groups"]
        for spoke in dr:
            if spoke == "hub":
                continue  # hub sources list the spokes present, which differ where DR spokes are missing
            for kind in ("network", "app"):
                assert [r["name"] for r in dr[spoke][kind]] == [r["name"] for r in primary[spoke][kind]], (env, spoke)


# ------------------------------------------------------------ the sample tickets


def _flows(name, spoke):
    return {r["name"] for r in rules(POLICIES[name]["groups"].get(spoke, {k: [] for k in KINDS}))}


def test_ritm0010042_is_a_new_rule_and_lands_at_024():
    for name in POLICIES:
        assert not any("northwindFs" in r and r.startswith("https-sett") for r in _flows(name, "sett")), name
    assert len(POLICIES["prod-eastus2"]["groups"]["sett"]["network"]) == 23  # so the next index is 024


def test_ritm0010043_is_new_and_public_port_2222_is_free():
    dnat = POLICIES["prod-eastus2"]["groups"]["xfer"]["dnat"]
    assert "sftp-northwind-to-xferSftp" not in {r["name"] for r in dnat}
    assert "2222" not in {p for r in dnat for p in r["destination_ports"]}


def test_ritm0010044_rule_exists_in_both_dev_sites():
    for name in ("dev-eastus2", "dev-centralus"):
        [rule] = [r for r in POLICIES[name]["groups"]["sett"]["app"] if r["name"] == "https-sett-to-northwindApi"]
        suffix = "-dr" if name.endswith("centralus") else ""
        assert rule["source_ip_groups"] == [f"ipg-sett-dev{suffix}"]
        assert rule["destination_fqdns"] == ["api.northwind.example"]
