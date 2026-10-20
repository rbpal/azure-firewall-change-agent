"""locate_address_for_env_site. Uses the real address plan for known facts and small
in-memory plans for edge cases. Each test fails if the matching rule, the
input checks or the answer's shape change."""

import json
from pathlib import Path

import pytest

import gateway
from errors import BadArguments
from data_readers.read_addressplan_routing import ADDRESS_PLAN, ROUTING, NetworkDataError, LocalSource
from tools.locate_address_for_env_site import locate_address_for_env_site

REPO = Path(__file__).resolve().parents[2]
REAL = LocalSource(REPO)


class TextSource:
    """An in-memory address plan for edge cases; routing is the real one unless given."""

    def __init__(self, text: str, routing: str | None = None):
        self.text, self.routing = text, routing

    def read(self, path):
        if path == ROUTING:
            return self.routing if self.routing is not None else REAL.read(path)
        return self.text

    @property
    def commit(self):
        return "abc123"


def call(address, source=REAL):
    return locate_address_for_env_site(None, {"address": address}, source)


# ---- known facts from the real plan

def test_spoke_address_maps_to_its_spoke():
    m = call("10.100.14.20")["match"]
    assert (m["cidr"], m["kind"], m["spoke"], m["env_site"]) == ("10.100.14.0/24", "spoke", "sett", "prod-eastus2")
    assert (m["vnet"], m["ip_group"], m["environment"], m["site"]) == ("vnet-sett-prod", "ipg-sett-prod", "prod", "primary")


def test_longest_prefix_wins_over_the_env_site_range():
    # 10.100.14.20 is in both 10.100.0.0/16 (env-site) and 10.100.14.0/24 (spoke)
    assert call("10.100.14.20")["match"]["kind"] == "spoke"


def test_dr_site_is_a_different_env_site():
    m = call("10.101.14.20")["match"]
    assert (m["spoke"], m["site"], m["env_site"]) == ("sett", "dr", "prod-centralus")


def test_known_hub_host_is_named():
    out = call("10.100.1.4")
    assert out["match"]["kind"] == "shared"
    assert out["host"] == "hubDns"


def test_address_in_env_site_but_no_spoke_matches_the_env_site():
    out = call("10.100.200.9")
    assert out["match"]["kind"] == "env-site"


def test_cidr_equal_to_a_spoke():
    out = call("10.100.14.0/24")
    assert out["match"]["spoke"] == "sett" and out["covers"] == []


def test_wide_cidr_lists_everything_it_covers():
    out = call("10.100.0.0/16")
    assert out["match"]["kind"] == "env-site"
    assert len(out["covers"]) == 6
    assert "10.100.14.0/24" in [c["cidr"] for c in out["covers"]]


def test_wider_than_any_range_is_not_found_but_lists_coverage():
    out = call("10.0.0.0/8")
    assert out["match"] is None
    assert len(out["covers"]) == 53
    assert "wider than every range" in out["reason"]


def test_partner_address_is_not_found():
    out = call("203.0.113.20")
    assert out["match"] is None and out["covers"] == []
    assert "not in the address plan" in out["reason"]


def test_answer_names_its_source():
    assert call("10.100.14.20")["source"] == {"files": [ADDRESS_PLAN, ROUTING], "commit": None}
    plan = "ranges:\n- {cidr: 10.0.0.0/16, kind: env-site, environment: lab, site: primary, region: eastus2}\n"
    assert call("10.0.0.1", TextSource(plan))["source"]["commit"] == "abc123"


# ---- input checks (the agent writes the arguments, so they are untrusted)

@pytest.mark.parametrize("bad", ["", "   ", "not-an-ip", "10.100.14", "999.1.1.1", "10.100.14.0/33", "2001:db8::1", None, 42])
def test_bad_addresses_are_refused(bad):
    with pytest.raises(BadArguments):
        call(bad)


def test_host_bits_set_is_refused_with_a_hint():
    with pytest.raises(BadArguments, match="did you mean 10.100.14.0/24"):
        call("10.100.14.5/24")


def test_unknown_argument_is_refused():
    with pytest.raises(BadArguments, match="only one argument"):
        locate_address_for_env_site(None, {"address": "10.100.14.20", "spoke": "sett"}, REAL)


def test_missing_argument_is_refused():
    with pytest.raises(BadArguments):
        locate_address_for_env_site(None, {}, REAL)


# ---- the network data itself

def test_duplicate_range_in_plan_is_a_network_data_error():
    plan = ("ranges:\n- {cidr: 10.0.0.0/16, kind: env-site, environment: lab, site: primary, region: eastus2}\n"
            "- {cidr: 10.0.0.0/16, kind: env-site, environment: dev, site: primary, region: eastus2}\n")
    with pytest.raises(NetworkDataError, match="duplicate"):
        call("10.0.0.1", TextSource(plan))


def test_unknown_kind_in_plan_is_a_network_data_error():
    plan = "ranges:\n- {cidr: 10.0.0.0/16, kind: mystery, environment: lab, site: primary, region: eastus2}\n"
    with pytest.raises(NetworkDataError, match="unknown kind"):
        call("10.0.0.1", TextSource(plan))


# ---- the hub firewall for each address

def test_spoke_address_names_its_hub_firewall_and_policy():
    m = call("10.100.14.20")["match"]
    assert (m["firewall"], m["firewall_policy"]) == ("afw-hub-prod-eastus2", "afwp-hub-prod-eastus2")


def test_dr_address_names_the_dr_hub_firewall():
    assert call("10.101.16.5")["match"]["firewall"] == "afw-hub-prod-centralus"


def test_each_env_site_names_a_different_firewall():
    addresses = [f"10.10{i}.14.20" for i in range(8)]
    firewalls = {call(a)["match"]["firewall"] for a in addresses}
    assert len(firewalls) == 8


def test_partner_address_names_no_firewall():
    out = call("203.0.113.20")
    assert out["match"] is None and "firewall" not in out


def test_env_site_missing_from_routing_is_a_network_data_error():
    plan = "ranges:\n- {cidr: 10.0.0.0/16, kind: env-site, environment: qa, site: primary, region: eastus2}\n"
    with pytest.raises(NetworkDataError, match="no hub in routing"):
        call("10.0.0.1", TextSource(plan))


def test_routing_entry_without_a_policy_is_a_network_data_error():
    routing = "env_sites:\n  prod-eastus2:\n    firewall: afw-hub-prod-eastus2\n"
    with pytest.raises(NetworkDataError, match="no firewall or policy"):
        call("10.100.14.20", TextSource(REAL.read(ADDRESS_PLAN), routing))

# ---- on-prem user subnets (address plan `onprem:`, routing `onprem:`)

def test_onprem_user_address_names_its_data_centre_and_connection():
    out = call("172.20.20.15")
    m = out["match"]
    assert (m["cidr"], m["kind"], m["location"]) == ("172.20.20.0/24", "users-wired", "onprem-primary")
    assert m["connection"] == "erc-onprem-primary" and m["ip_group"] == "ipg-onprem-primary"
    assert "reason" not in out


def test_onprem_secondary_is_its_own_site():
    m = call("172.24.96.0/24")["match"]
    assert (m["location"], m["kind"], m["connection"]) == ("onprem-secondary", "users-vpn", "erc-onprem-secondary")


def test_onprem_address_has_no_env_site_or_firewall_of_its_own():
    m = call("172.20.64.1")["match"]
    assert m["env_site"] is None and m["firewall"] is None and m["firewall_policy"] is None
    assert "environment" not in m and "site" not in m
    assert m["inspection"].startswith("assumed, not verified:")


def test_onprem_gap_is_not_in_the_plan():
    out = call("172.20.200.0/24")
    assert out["match"] is None and out["covers"] == []
    assert out["reason"] == "not in the address plan (Azure or on-prem)"


def test_wide_onprem_cidr_lists_the_user_subnets_it_covers():
    out = call("172.24.0.0/16")
    assert out["match"] is None and "wider than every range" in out["reason"]
    assert [c["cidr"] for c in out["covers"]] == ["172.24.10.0/23", "172.24.12.0/24", "172.24.14.0/24",
                                                  "172.24.64.0/22", "172.24.96.0/24"]


def test_every_onprem_prefix_in_routing_is_in_the_address_plan():
    import yaml
    plan = {r["cidr"]: r["location"] for r in yaml.safe_load(REAL.read(ADDRESS_PLAN))["onprem"]}
    routing = yaml.safe_load(REAL.read(ROUTING))["onprem"]
    assert {c: site for site, link in routing.items() for c in link["prefixes"]} == plan


def test_onprem_site_without_a_connection_is_a_network_data_error():
    routing = REAL.read(ROUTING).split("\nonprem:")[0] + "\n"
    with pytest.raises(NetworkDataError, match="has no connection in routing"):
        call("172.20.20.15", TextSource(REAL.read(ADDRESS_PLAN), routing))


def test_onprem_row_with_unknown_kind_is_a_network_data_error():
    plan = REAL.read(ADDRESS_PLAN).replace("kind: users-vpn", "kind: servers", 1)
    with pytest.raises(NetworkDataError, match="unknown on-prem kind"):
        call("10.100.14.20", TextSource(plan))


# ---- through the gateway

def test_gateway_passes_arguments_to_the_tool(allowed_context):
    out = json.loads(gateway.run(allowed_context({"address": "10.100.14.20"}), locate_address_for_env_site, source=REAL))
    assert out["match"]["spoke"] == "sett"


def test_gateway_turns_bad_arguments_into_an_answer(allowed_context):
    out = json.loads(gateway.run(allowed_context({"address": "nope"}), locate_address_for_env_site, source=REAL))
    assert out["error"] == "bad_arguments" and "not an IPv4" in out["reason"]


def test_gateway_hides_detail_of_unexpected_failures(allowed_context):
    out = json.loads(gateway.run(allowed_context({"address": "10.0.0.1"}), locate_address_for_env_site, source=TextSource("not: [valid")))
    assert out == {"error": "tool_failed"}
