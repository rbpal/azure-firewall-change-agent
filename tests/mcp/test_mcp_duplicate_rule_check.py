"""duplicate_rule_check. Uses the real rules for known facts and small in-memory
rules files for edge cases. Each test fails if the coverage maths, the input
checks or the answer's shape change."""

import json
from pathlib import Path

import pytest

import gateway
from errors import BadArguments
from data_readers.read_addressplan_routing import LocalSource
from tools.duplicate_rule_check import duplicate_rule_check

REPO = Path(__file__).resolve().parents[2]
REAL = LocalSource(REPO)
PORT_FILE = "infra/envs/dev-eastus2/firewall_policy_rule_collection_groups/port.tfvars"


class OverrideSource:
    """The real repo, with some files replaced by in-memory text."""

    def __init__(self, files: dict[str, str], commit: str = "abc123"):
        self.files, self.commit = files, commit

    def read(self, path):
        return self.files[path] if path in self.files else REAL.read(path)


def port_file(rules: str, kind: str = "network", action: str = "Allow") -> OverrideSource:
    """Replace dev-eastus2 port.tfvars with one collection holding the given rules."""
    text = f"""
port = {{
  name     = "port"
  priority = 200
  {kind}_rule_collections = {{
    test-collection = {{
      name     = "test-collection"
      priority = 2000
      action   = "{action}"
      rules = {{
{rules}
      }}
    }}
  }}
}}
"""
    return OverrideSource({PORT_FILE: text})


def check(rule, rule_type="network", env_site="dev-eastus2", source=REAL):
    return duplicate_rule_check(None, {"env_site": env_site, "type": rule_type, "rule": rule}, source)


def keys(out):
    return [(m["relation"], m["key"]) for m in out["matches"]]


AMQPS = {"protocols": ["TCP"], "source_addresses": ["10.104.17.0/24"],
         "destination_addresses": ["198.51.100.48/28"], "destination_ports": ["5671"]}


# ---- known facts from the real rules

def test_same_rule_is_a_duplicate():
    out = check(AMQPS)
    assert out["already_allowed"] is True
    assert keys(out) == [("duplicate", "001-amqps-port-to-lamnaMq")]
    m = out["matches"][0]
    assert (m["type"], m["collection"], m["file"]) == ("network", "allow-port-network-rules", PORT_FILE)


def test_narrower_source_is_covered_not_duplicate():
    assert keys(check({**AMQPS, "source_addresses": ["10.104.17.10/32"]})) == [("covers", "001-amqps-port-to-lamnaMq")]


def test_ip_group_is_swapped_for_its_addresses():
    """ipg-port-dev holds the port subnet and 13 on-prem user subnets, so the CIDR-only rule 001 does not cover it."""
    rule = {**AMQPS, "source_addresses": [], "source_ip_groups": ["ipg-port-dev"]}
    out = check(rule)
    assert out["matches"] == [] and out["already_allowed"] is False


def test_other_port_is_not_allowed():
    out = check({**AMQPS, "destination_ports": ["5672"]})
    assert out["already_allowed"] is False and out["matches"] == []


def test_wider_source_is_not_allowed():
    assert check({**AMQPS, "source_addresses": ["10.104.0.0/16"]})["matches"] == []


def test_other_protocol_is_not_allowed():
    assert check({**AMQPS, "protocols": ["UDP"]})["matches"] == []


def test_hub_file_is_checked():
    rule = {"protocols": ["UDP"], "source_addresses": ["10.104.14.0/24"],
            "destination_addresses": ["10.104.1.4/32"], "destination_ports": ["53"]}
    out = check(rule)
    assert keys(out) == [("covers", "001-dns-spokes-to-hubDns")]
    assert out["matches"][0]["file"].endswith("/hub.tfvars")


def test_a_cidr_request_inside_a_group_rule_is_covered_but_not_like_for_like():
    """Rule 001 names ipg-port-dev, which holds 10.104.17.0/24 and more: the firewall allows the traffic,
    but a CIDR ticket is not met by a group rule (STD-COLL-03), so already_allowed is False."""
    rule = {"protocols": ["Https:443"], "source_addresses": ["10.104.17.0/24"],
            "destination_fqdns": ["api.fabrikam.example"]}
    out = check(rule, "application")
    assert keys(out) == [("covers", "001-https-port-to-fabrikamApi")]
    assert out["matches"][0]["like_for_like"] is False and out["already_allowed"] is False


def test_a_request_naming_the_rules_group_is_a_like_for_like_duplicate():
    rule = {"protocols": ["Https:443"], "source_ip_groups": ["ipg-port-dev"],
            "destination_fqdns": ["api.fabrikam.example"]}
    out = check(rule, "application")
    assert keys(out) == [("duplicate", "001-https-port-to-fabrikamApi")]
    assert out["matches"][0]["like_for_like"] is True and out["already_allowed"] is True


ONPREM_RULES = """
        "001-https-onprem-to-portalFs" = {
          name                  = "https-onprem-to-portalFs"
          protocols             = ["TCP"]
          source_ip_groups      = ["ipg-onprem-primary", "ipg-onprem-secondary"]
          destination_addresses = ["10.104.17.0/24"]
          destination_ports     = ["443"]
        }
        "002-syslog-port-to-onpremPrimary" = {
          name                  = "syslog-port-to-onpremPrimary"
          protocols             = ["UDP"]
          source_addresses      = ["10.104.17.0/24"]
          destination_ip_groups = ["ipg-onprem-primary"]
          destination_ports     = ["514"]
        }
"""


@pytest.mark.parametrize("groups, relation, like", [
    (["ipg-onprem-primary", "ipg-onprem-secondary"], "duplicate", True),
    (["ipg-onprem-primary"], "covers", True),
    (["ipg-onprem-secondary"], "covers", True),
], ids=["both on-prem groups", "primary only", "secondary only"])
def test_on_prem_groups_as_sources(groups, relation, like):
    """Users at either on-prem site, or both, reaching the portal through rule 001."""
    rule = {"protocols": ["TCP"], "source_ip_groups": groups,
            "destination_addresses": ["10.104.17.0/24"], "destination_ports": ["443"]}
    out = check(rule, source=port_file(ONPREM_RULES))
    assert keys(out) == [(relation, "001-https-onprem-to-portalFs")]
    assert out["matches"][0]["like_for_like"] is like and out["already_allowed"] is like


def test_on_prem_group_as_destination():
    rule = {"protocols": ["UDP"], "source_addresses": ["10.104.17.0/24"],
            "destination_ip_groups": ["ipg-onprem-primary"], "destination_ports": ["514"]}
    out = check(rule, source=port_file(ONPREM_RULES))
    assert keys(out) == [("duplicate", "002-syslog-port-to-onpremPrimary")] and out["already_allowed"] is True


def test_the_secondary_group_is_not_covered_by_a_primary_group_rule():
    """Rule 002 sends to on-prem primary users only; the secondary group is a different set of subnets."""
    rule = {"protocols": ["UDP"], "source_addresses": ["10.104.17.0/24"],
            "destination_ip_groups": ["ipg-onprem-secondary"], "destination_ports": ["514"]}
    assert check(rule, source=port_file(ONPREM_RULES))["matches"] == []


@pytest.mark.parametrize("side", ["source", "destination"])
def test_a_user_subnet_cidr_is_not_like_for_like_with_an_on_prem_group_rule(side):
    """172.20.64.0/22 is in ipg-onprem-primary, but a CIDR request is never met by the group rule."""
    if side == "source":
        rule = {"protocols": ["TCP"], "source_addresses": ["172.20.64.0/22"],
                "destination_addresses": ["10.104.17.0/24"], "destination_ports": ["443"]}
    else:
        rule = {"protocols": ["UDP"], "source_addresses": ["10.104.17.0/24"],
                "destination_addresses": ["172.20.64.0/22"], "destination_ports": ["514"]}
    out = check(rule, source=port_file(ONPREM_RULES))
    assert [m["relation"] for m in out["matches"]] == ["covers"]
    assert out["matches"][0]["like_for_like"] is False and out["already_allowed"] is False


def test_application_rule_to_another_name_is_not_allowed():
    rule = {"protocols": ["Https:443"], "source_ip_groups": ["ipg-port-dev"],
            "destination_fqdns": ["api2.fabrikam.example"]}
    assert check(rule, "application")["matches"] == []


DNAT = {"protocols": ["TCP"], "source_addresses": ["203.0.113.48/28"], "destination_address": "192.0.2.10",
        "destination_ports": ["2221"], "translated_address": "10.100.20.14", "translated_port": "22"}


def test_same_dnat_rule_is_a_duplicate():
    out = check(DNAT, "dnat", "prod-eastus2")
    assert keys(out) == [("duplicate", "001-sftp-woodgrove-to-xferSftp")]


def test_dnat_to_another_internal_port_is_not_a_duplicate():
    assert check({**DNAT, "translated_port": "2222"}, "dnat", "prod-eastus2")["matches"] == []


def test_answer_names_every_file_read_and_the_commit():
    out = check(AMQPS, source=OverrideSource({}, commit="sha-1"))
    assert out["source"]["commit"] == "sha-1"
    assert "infra/envs/dev-eastus2/ip-groups.tfvars" in out["source"]["files"]
    assert "infra/envs/dev-eastus2/firewall_policy_rule_collection_groups/hub.tfvars" in out["source"]["files"]
    assert len(out["source"]["files"]) == 7


# ---- coverage maths, on in-memory rules

RULE = """        "001-test" = {{
          name                  = "test"
          protocols             = {protocols}
          source_addresses      = {sources}
          destination_addresses = {destinations}
          destination_ports     = {ports}
        }}"""


def network(protocols='["TCP"]', sources='["10.104.17.0/24"]', destinations='["198.51.100.48/28"]', ports='["443"]'):
    return RULE.format(protocols=protocols, sources=sources, destinations=destinations, ports=ports)


NEW = {"protocols": ["TCP"], "source_addresses": ["10.104.17.0/24"],
       "destination_addresses": ["198.51.100.48/28"], "destination_ports": ["443"]}


def test_two_halves_cover_the_whole_range():
    source = port_file(network(sources='["10.104.17.0/25", "10.104.17.128/25"]'))
    assert keys(check(NEW, source=source)) == [("duplicate", "001-test")]


def test_one_half_does_not_cover_the_whole_range():
    assert check(NEW, source=port_file(network(sources='["10.104.17.0/25"]')))["matches"] == []


def test_port_ranges_join_up():
    source = port_file(network(ports='["440-445", "446-450"]'))
    assert keys(check({**NEW, "destination_ports": ["443-448"]}, source=source)) == [("covers", "001-test")]


def test_port_range_with_a_gap_does_not_cover():
    source = port_file(network(ports='["440-444", "446-450"]'))
    assert check({**NEW, "destination_ports": ["443-448"]}, source=source)["matches"] == []


def test_star_covers_every_address_and_port():
    source = port_file(network(destinations='["*"]', ports='["*"]'))
    assert keys(check(NEW, source=source)) == [("covers", "001-test")]


def test_any_protocol_covers_tcp():
    assert keys(check(NEW, source=port_file(network(protocols='["Any"]')))) == [("covers", "001-test")]


def test_deny_collection_never_counts_as_allowed():
    assert check(NEW, source=port_file(network(), action="Deny"))["matches"] == []


def test_network_rule_to_any_address_covers_an_application_rule():
    source = port_file(network(destinations='["*"]'))
    rule = {"protocols": ["Https:443"], "source_addresses": ["10.104.17.0/24"], "destination_fqdns": ["api.x.example"]}
    assert keys(check(rule, "application", source=source)) == [("covers", "001-test")]


def test_network_rule_on_another_port_does_not_cover_an_application_rule():
    source = port_file(network(destinations='["*"]', ports='["80"]'))
    rule = {"protocols": ["Https:443"], "source_addresses": ["10.104.17.0/24"], "destination_fqdns": ["api.x.example"]}
    assert check(rule, "application", source=source)["matches"] == []


APP = """        "001-test" = {{
          name              = "test"
          protocols         = ["Https:443"]
          source_addresses  = ["10.104.17.0/24"]
          destination_fqdns = {fqdns}
        }}"""


@pytest.mark.parametrize("pattern, name, allowed", [
    ('["*.fabrikam.example"]', "api.fabrikam.example", True),
    ('["*.fabrikam.example"]', "a.b.fabrikam.example", True),
    ('["*.fabrikam.example"]', "fabrikam.example", False),     # a wildcard does not match the bare domain
    ('["*.fabrikam.example"]', "evilfabrikam.example", False),
    ('["API.Fabrikam.example"]', "api.fabrikam.example", True),  # names are not case-sensitive
])
def test_wildcard_names(pattern, name, allowed):
    rule = {"protocols": ["Https:443"], "source_addresses": ["10.104.17.0/24"], "destination_fqdns": [name]}
    out = check(rule, "application", source=port_file(APP.format(fqdns=pattern), kind="application"))
    assert out["already_allowed"] is allowed


# ---- arguments

@pytest.mark.parametrize("arguments", [
    {"env_site": "dev-westus", "type": "network", "rule": NEW},
    {"env_site": "dev-eastus2", "type": "firewall", "rule": NEW},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "destination_fqdns_tags": ["x"]}},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "destination_ports": []}},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "source_addresses": []}},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "destination_addresses": []}},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "protocols": []}},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "source_addresses": ["10.104.17.5/24"]}},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "source_addresses": "10.104.17.0/24"}},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "source_ip_groups": ["ipg-nope"]}},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "destination_ports": ["https"]}},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "destination_ports": ["70000"]}},
    {"env_site": "dev-eastus2", "type": "network", "rule": {**NEW, "destination_ports": ["450-440"]}},
    {"env_site": "dev-eastus2", "type": "application", "rule": {"protocols": ["Https:abc"],
                                                               "source_addresses": ["10.104.17.0/24"],
                                                               "destination_fqdns": ["a.example"]}},
    {"env_site": "dev-eastus2", "type": "network", "rule": NEW, "branch": "agent/x"},
    {"env_site": "dev-eastus2", "type": "network"},
])
def test_bad_arguments_are_refused(arguments):
    with pytest.raises(BadArguments):
        duplicate_rule_check(None, arguments, REAL)


# ---- through the gateway

def test_gateway_returns_the_matches(allowed_context):
    context = allowed_context({"env_site": "dev-eastus2", "type": "network", "rule": AMQPS})
    out = json.loads(gateway.run(context, duplicate_rule_check, source=REAL))
    assert out["matches"][0]["key"] == "001-amqps-port-to-lamnaMq"


def test_gateway_turns_a_bad_rule_into_bad_arguments(allowed_context):
    context = allowed_context({"env_site": "dev-eastus2", "type": "nope", "rule": AMQPS})
    assert json.loads(gateway.run(context, duplicate_rule_check, source=REAL))["error"] == "bad_arguments"
