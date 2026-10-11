"""tools/read_env_site_ipgroup.py, the rules reader for the duplicate rule tool. Uses the real tfvars
for known facts and small in-memory files for edge cases. Each test fails if
the file choice, the parsing or the answer's shape change."""

import shutil
from pathlib import Path

import pytest

from tools.read_addressplan_routing import ROUTING, LocalSource, NetworkDataError
from tools.read_env_site_ipgroup import parse_rules, read_env_site, read_ip_groups

REPO = Path(__file__).resolve().parents[2]
REAL = LocalSource(REPO)
ENVS = sorted(p.name for p in (REPO / "infra/envs").iterdir() if p.is_dir())

PORT = """
port = {
  name     = "port"
  priority = 200
  network_rule_collections = {
    allow-port-network-rules = {
      name     = "allow-port-network-rules"
      priority = 2000
      action   = "Allow"
      rules = {
        "002-https-port-to-settApi" = {
          name                  = "https-port-to-settApi"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.17.0/24"]
          destination_addresses = ["10.104.14.0/24"]
          destination_ports     = ["443"]
        }
        "001-amqps-port-to-lamnaMq" = {
          name                  = "amqps-port-to-lamnaMq"
          protocols             = ["TCP"]
          source_addresses      = ["10.104.17.0/24"]
          destination_addresses = ["198.51.100.48/28"]
          destination_ports     = ["5671"]
        }
      }
    }
  }
}
"""


def parse(text=PORT, name="port"):
    return parse_rules(text, name, "port.tfvars")


def group(groups, name):
    found = [g for g in groups if g["rule_collection_group"] == name]
    assert len(found) == 1
    return found[0]


def collection(g, kind):
    found = [c for c in g["collections"] if c["type"] == kind]
    assert len(found) == 1
    return found[0]


# ---- known facts from the real files

def test_env_site_read_includes_the_hub_and_every_spoke():
    groups = read_env_site(REAL, "dev-eastus2")
    assert sorted(g["rule_collection_group"] for g in groups) == ["hub", "ledg", "port", "rprt", "sett", "xfer"]
    assert group(groups, "port")["file"] == "infra/envs/dev-eastus2/firewall_policy_rule_collection_groups/port.tfvars"


def test_env_site_read_has_only_its_own_spokes():
    names = [g["rule_collection_group"] for g in read_env_site(REAL, "lab-centralus")]
    assert sorted(names) == ["hub", "ledg", "sett", "xfer"]


def test_network_rule_fields_are_parsed_without_quotes():
    net = collection(group(read_env_site(REAL, "dev-eastus2"), "port"), "network")
    assert (net["name"], net["priority"], net["action"]) == ("allow-port-network-rules", 2000, "Allow")
    assert [r["key"] for r in net["rules"]] == ["001-amqps-port-to-lamnaMq", "002-https-port-to-settApi",
                                                "003-https-port-to-fourthcoffeeFs", "004-https-port-to-tailspinFs"]
    assert net["rules"][0] == {"key": "001-amqps-port-to-lamnaMq", "name": "amqps-port-to-lamnaMq",
                               "protocols": ["TCP"], "source_addresses": ["10.104.17.0/24"],
                               "destination_addresses": ["198.51.100.48/28"], "destination_ports": ["5671"]}


def test_application_rules_keep_ip_groups_and_fqdns():
    app = collection(group(read_env_site(REAL, "dev-eastus2"), "port"), "application")
    assert app["rules"][0]["source_ip_groups"] == ["ipg-port-dev"]
    assert app["rules"][0]["destination_fqdns"] == ["api.fabrikam.example"]


def test_dnat_collection_is_typed_dnat_and_listed_first():
    xfer = group(read_env_site(REAL, "prod-eastus2"), "xfer")
    assert xfer["collections"][0]["type"] == "dnat"
    dnat = collection(xfer, "dnat")
    assert dnat["action"] == "Dnat"
    assert dnat["rules"][0]["translated_port"] == "22"


def test_ip_groups_map_names_to_cidrs():
    groups = read_ip_groups(REAL, "dev-eastus2")
    assert groups["ipg-port-dev"] == ["10.104.17.0/24"]


@pytest.mark.parametrize("env_site", ENVS)
def test_every_env_site_parses(env_site):
    groups = read_env_site(REAL, env_site)
    assert all(g["collections"] and all(c["rules"] for c in g["collections"]) for g in groups)
    assert read_ip_groups(REAL, env_site)


@pytest.mark.parametrize("env_site", ENVS)
def test_every_ip_group_a_rule_names_exists(env_site):
    known = read_ip_groups(REAL, env_site)
    for g in read_env_site(REAL, env_site):
        for c in g["collections"]:
            for r in c["rules"]:
                for name in r.get("source_ip_groups", []) + r.get("destination_ip_groups", []):
                    assert name in known, (env_site, r["key"], name)


# ---- order

def test_rules_are_sorted_by_key_not_file_order():
    assert [r["key"] for r in collection(parse(), "network")["rules"]] == [
        "001-amqps-port-to-lamnaMq", "002-https-port-to-settApi"]


def test_network_rules_list_before_application_rules_whatever_the_priority():
    # Azure applies network rules before application rules; priority orders within a type only.
    app_first = PORT.replace("port = {", """port = {
  application_rule_collections = {
    allow-port-app-rules = {
      name     = "allow-port-app-rules"
      priority = 100
      action   = "Allow"
      rules    = { "001-https-port-to-x" = { name = "https-port-to-x" } }
    }
  }""", 1)
    assert [c["type"] for c in parse(app_first)["collections"]] == ["network", "application"]


def copy_env_site(tmp_path, env_site="dev-eastus2"):
    """Copy routing and one env-site's files, so a test can change them."""
    shutil.copytree(REPO / "infra/envs" / env_site, tmp_path / "infra/envs" / env_site)
    (tmp_path / ROUTING).parent.mkdir(parents=True)
    shutil.copy(REPO / ROUTING, tmp_path / ROUTING)
    return LocalSource(tmp_path), tmp_path / "infra/envs" / env_site / "firewall_policy_rule_collection_groups"


def test_groups_are_sorted_by_priority(tmp_path):
    source, folder = copy_env_site(tmp_path)
    port = folder / "port.tfvars"
    port.write_text(port.read_text().replace("priority            = 200", "priority            = 100", 1))
    assert read_env_site(source, "dev-eastus2")[0]["rule_collection_group"] == "port"


def test_files_come_from_routing_not_the_folder(tmp_path):
    source, folder = copy_env_site(tmp_path)
    (folder / "extra.tfvars").write_text('extra = {\n  name = "extra"\n}\n')
    assert "extra" not in [g["rule_collection_group"] for g in read_env_site(source, "dev-eastus2")]


# ---- every read is fresh

def test_a_rule_added_after_a_read_shows_on_the_next_read(tmp_path):
    source, folder = copy_env_site(tmp_path)
    path = folder / "port.tfvars"
    before = collection(group(read_env_site(source, "dev-eastus2"), "port"), "network")["rules"]
    path.write_text(path.read_text().replace('"001-amqps', '"005-ssh-port-to-xferSftp" = {\n name = "ssh"\n }\n "001-amqps', 1))
    after = collection(group(read_env_site(source, "dev-eastus2"), "port"), "network")["rules"]
    assert len(after) == len(before) + 1 and after[-1]["key"] == "005-ssh-port-to-xferSftp"


# ---- malformed files are errors, not empty answers

@pytest.mark.parametrize("text", [
    "port = {",                                          # not HCL
    PORT.replace("port = {", "sett = {", 1),             # wrong variable for the file
    PORT + '\nextra = { name = "x" }\n',                 # a second variable
    PORT.replace("network_rule_collections", "nat64_rule_collections"),  # unknown type
])
def test_malformed_rules_file_raises(text):
    with pytest.raises(NetworkDataError):
        parse(text)


def test_unknown_env_site_raises():
    with pytest.raises(NetworkDataError):
        read_env_site(REAL, "dev-westus")


def test_ip_group_without_cidrs_raises(tmp_path):
    path = tmp_path / "infra/envs/dev-eastus2/ip-groups.tfvars"
    path.parent.mkdir(parents=True)
    path.write_text('ip_groups = {\n  ipg-x = {\n    name = "ipg-x"\n  }\n}\n')
    with pytest.raises(NetworkDataError):
        read_ip_groups(LocalSource(tmp_path), "dev-eastus2")
