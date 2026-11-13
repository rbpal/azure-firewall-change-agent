"""locate_address_for_env_site. Uses the real address plan for known facts and small
in-memory plans for edge cases. Each test fails if the matching rule, the
input checks or the answer's shape change."""

import json
from pathlib import Path

import pytest
import yaml

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


def test_host_bits_set_is_refused_with_both_readings_and_no_choice():
    with pytest.raises(BadArguments) as info:
        call("10.100.14.5/24")
    assert "the host 10.100.14.5/32 or the subnet 10.100.14.0/24" in str(info.value)
    assert "did you mean" not in str(info.value)


# ---- facts the engineer reviews: wider than the plan, and no owner

def test_onprem_cidr_wider_than_its_plan_range_names_the_extra_block():
    out = call("172.20.20.0/23")
    assert out["wider_than_plan"] == {"plan_ranges": ["172.20.20.0/24"], "extra": ["172.20.21.0/24"],
                                      "extra_addresses": 256}


def test_azure_cidr_spanning_two_spokes_is_wider_than_plan_with_no_extra_block():
    out = call("10.104.14.0/23")
    assert out["match"]["kind"] == "env-site"
    assert out["wider_than_plan"] == {"plan_ranges": ["10.104.14.0/24", "10.104.15.0/24"], "extra": [],
                                      "extra_addresses": 0}


def test_address_in_an_env_site_that_no_spoke_owns_says_so():
    out = call("10.104.40.0/24")
    assert out["match"]["env_site"] == "dev-eastus2" and "wider_than_plan" not in out
    assert out["no_owner"].startswith("inside dev-eastus2, but no spoke or shared range")


@pytest.mark.parametrize("address", ["172.20.20.0/25", "172.20.20.15", "10.104.14.0/24", "10.104.14.0/25"])
def test_a_narrower_or_exact_address_is_neither_wider_nor_unowned(address):
    out = call(address)
    assert out["match"] is not None and "wider_than_plan" not in out and "no_owner" not in out


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
    assert m["firewall_public_ip"] == "192.0.2.10"  # routing.yaml; a DNAT rule's destination (RB-02-3)


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


# ---- IP groups: every plan range that lists the group, and their origin

GROUP_PLAN = ("ranges:\n"
              "- {cidr: 10.0.0.0/16, kind: env-site, environment: lab, site: primary, region: eastus2}\n"
              "- {cidr: 10.0.2.0/24, kind: spoke, environment: lab, site: primary, region: eastus2, spoke: app, ip_group: ipg-app-lab}\n"
              "- {cidr: 10.0.1.0/24, kind: spoke, environment: lab, site: primary, region: eastus2, spoke: app, ip_group: ipg-app-lab}\n"
              "- {cidr: 10.0.3.0/24, kind: spoke, environment: lab, site: primary, region: eastus2, spoke: mix, ip_group: ipg-mix-lab}\n"
              "onprem:\n"
              "- {cidr: 172.20.10.0/23, location: onprem-primary, kind: users-wired, ip_group: ipg-mix-lab}\n")


def test_spoke_group_is_its_one_azure_range():
    out = call("ipg-ledg-prod-dr")
    assert out["origin"] == "azure" and len(out["matches"]) == 1
    m = out["matches"][0]
    assert (m["spoke"], m["environment"], m["site"], m["env_site"], m["ip_group"]) == \
        ("ledg", "prod", "dr", "prod-centralus", "ipg-ledg-prod-dr")
    assert m["firewall"] == "afw-hub-prod-centralus"


def test_onprem_primary_group_lists_its_eight_user_ranges():
    out = call("ipg-onprem-primary")
    assert out["origin"] == "onprem" and len(out["matches"]) == 8
    assert {m["location"] for m in out["matches"]} == {"onprem-primary"}
    assert all(m["env_site"] is None and m["firewall"] is None for m in out["matches"])


def test_onprem_secondary_group_lists_its_five_user_ranges():
    out = call("ipg-onprem-secondary")
    assert out["origin"] == "onprem" and len(out["matches"]) == 5
    assert {m["location"] for m in out["matches"]} == {"onprem-secondary"}


def test_group_no_range_lists_has_no_origin_and_no_guess():
    out = call("ipg-pays-dev")
    assert out["matches"] == [] and out["origin"] is None
    assert out["reason"].startswith("no range in the address plan lists this IP group")
    assert "ambiguous" not in out


def test_group_on_several_azure_ranges_lists_each_in_address_order():
    out = call("ipg-app-lab", TextSource(GROUP_PLAN))
    assert out["origin"] == "azure" and [m["cidr"] for m in out["matches"]] == ["10.0.1.0/24", "10.0.2.0/24"]
    assert "ambiguous" not in out


def test_group_on_azure_and_onprem_ranges_is_mixed_and_says_so():
    out = call("ipg-mix-lab", TextSource(GROUP_PLAN))
    assert out["origin"] == "mixed" and "Azure and on-prem" in out["ambiguous"]
    assert [m["cidr"] for m in out["matches"]] == ["10.0.3.0/24", "172.20.10.0/23"]
    assert out["matches"][0]["env_site"] == "lab-eastus2" and out["matches"][1]["location"] == "onprem-primary"


def test_every_group_in_the_real_plan_has_one_origin():
    plan = yaml.safe_load(REAL.read(ADDRESS_PLAN))
    groups = {r["ip_group"] for key in ("ranges", "onprem") for r in plan[key] if r.get("ip_group")}
    origins = {g: call(g)["origin"] for g in groups}
    assert len(groups) > 30 and {g: o for g, o in origins.items() if o not in ("azure", "onprem")} == {}


def test_a_group_matches_only_its_exact_name():
    out = call("ipg-ledg-prod")
    assert [m["ip_group"] for m in out["matches"]] == ["ipg-ledg-prod"]


def test_group_answer_names_its_source():
    out = call("ipg-app-lab", TextSource(GROUP_PLAN))
    assert out["source"] == {"files": [ADDRESS_PLAN, ROUTING], "commit": "abc123"}
    assert out["input"] == "ipg-app-lab"


@pytest.mark.parametrize("bad", ["ipg-", "ipg--ledg", "ipg-ledg-", "IPG-ledg-prod-dr", "ipg-Ledg-prod-dr",
                                 "ipg_ledg_prod", "ipg-ledg prod", "ipg-ledg-prod-dr;x", "ipg-lédg"])
def test_malformed_group_names_are_refused_never_corrected(bad):
    with pytest.raises(BadArguments) as info:
        call(bad)
    assert "IP group name" in str(info.value) and "did you mean" not in str(info.value)


def test_a_cidr_answer_keeps_its_shape():
    out = call("10.103.15.0/24")
    assert set(out) == {"input", "match", "covers", "source"}
    assert out["match"]["spoke"] == "rprt" and out["match"]["env_site"] == "stage-centralus"


# ---- address_space: what the number is, for an address no plan range contains

ONE_RANGE_PLAN = "ranges:\n- {cidr: 100.64.0.0/24, kind: spoke, environment: lab, site: primary, region: eastus2, spoke: app}\n"


@pytest.mark.parametrize("address, space", [
    ("9.255.255.255/32", "non_rfc1918"), ("10.0.0.0/32", "rfc1918"), ("10.255.255.255/32", "rfc1918"), ("11.0.0.0/32", "non_rfc1918"),
    ("172.15.255.255/32", "non_rfc1918"), ("172.16.0.0/32", "rfc1918"), ("172.31.255.255/32", "rfc1918"), ("172.32.0.0/32", "non_rfc1918"),
    ("192.167.255.255/32", "non_rfc1918"), ("192.168.0.0/32", "rfc1918"), ("192.168.255.255/32", "rfc1918"), ("192.169.0.0/32", "non_rfc1918"),
])
def test_address_space_at_each_rfc1918_edge(address, space):
    assert call(address, TextSource(ONE_RANGE_PLAN))["address_space"] == space


@pytest.mark.parametrize("address", ["10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "172.20.200.0/24"])
def test_a_whole_block_or_a_range_inside_one_is_rfc1918(address):
    assert call(address, TextSource(ONE_RANGE_PLAN))["address_space"] == "rfc1918"


@pytest.mark.parametrize("address", ["8.0.0.0/6", "10.0.0.0/7", "172.0.0.0/8", "172.0.0.0/11", "192.168.0.0/15", "192.0.0.0/8", "0.0.0.0/0"])
def test_a_range_that_partly_overlaps_rfc1918_is_mixed(address):
    assert call(address, TextSource(ONE_RANGE_PLAN))["address_space"] == "mixed"


@pytest.mark.parametrize("address", ["192.0.2.0/24", "198.51.100.0/24", "198.51.100.32/28", "203.0.113.0/24", "203.0.113.5/32", "100.65.0.0/24"])
def test_documentation_and_other_private_looking_ranges_are_non_rfc1918(address):
    out = call(address)
    assert out["match"] is None and out["address_space"] == "non_rfc1918"


def test_the_answer_never_calls_non_rfc1918_public_or_internet():
    text = json.dumps(call("198.51.100.32/28")).lower()
    assert "public" not in text and "internet" not in text


def test_the_two_tickets_lookups_alone_could_not_separate_now_differ():
    assert call("172.20.200.0/24")["address_space"] == "rfc1918"  # RITM0011053
    assert call("198.51.100.32/28")["address_space"] == "non_rfc1918"  # RITM0011060


def test_a_plan_range_has_no_address_space_even_inside_rfc1918():
    assert "address_space" not in call("10.103.15.0/24")
    assert "address_space" not in call("10.104.40.0/24")  # inside an env-site, owned by no spoke
    assert "address_space" not in call("172.20.20.0/24")  # on-prem
    assert "address_space" not in call("ipg-pays-dev")


def test_a_cidr_wider_than_its_plan_range_keeps_both_facts():
    out = call("172.24.12.0/23")  # RITM0011057: the runbook needs wider_than_plan, the instructions need where it sits
    assert out["address_space"] == "rfc1918" and out["wider_than_plan"]["plan_ranges"] == ["172.24.12.0/24"]
    assert [m["location"] for m in out["covers"]] == ["onprem-secondary"]


def test_all_ipv4_zero_is_mixed_and_covers_both_sides():
    out = call("0.0.0.0/0")
    assert out["match"] is None and out["address_space"] == "mixed" and out["wider_than_plan"]
    assert {bool(m.get("location")) for m in out["covers"]} == {True, False}


@pytest.mark.parametrize("wild", ["*", "any", "ipg-*", "10.*", "0.0.0.0/33"])
def test_a_wildcard_is_refused_not_classified(wild):
    with pytest.raises(BadArguments):
        call(wild)


def test_the_answer_comes_from_explicit_blocks_not_is_private():
    import ipaddress
    assert ipaddress.ip_network("198.51.100.0/24").is_private  # the trap this tool avoids
    assert call("198.51.100.0/24")["address_space"] == "non_rfc1918"


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


def test_gateway_passes_a_group_name_to_the_tool(allowed_context):
    out = json.loads(gateway.run(allowed_context({"address": "ipg-onprem-secondary"}), locate_address_for_env_site, source=REAL))
    assert out["origin"] == "onprem" and len(out["matches"]) == 5
