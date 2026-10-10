"""locate_address. Uses the real address plan for known facts and small
in-memory plans for edge cases. Each test fails if the matching rule, the
input checks or the answer's shape change."""

import json
from pathlib import Path

import pytest

import gateway
from errors import BadArguments
from estate import EstateError, LocalSource
from tools.locate_address import locate_address

REPO = Path(__file__).resolve().parents[2]
REAL = LocalSource(REPO)


class TextSource:
    """An in-memory address plan for edge cases."""

    def __init__(self, text: str):
        self.text = text

    def read(self, path):
        return self.text

    @property
    def commit(self):
        return "abc123"


def call(address, source=REAL):
    return locate_address(None, {"address": address}, source)


# ---- known facts from the real plan

def test_spoke_address_maps_to_its_spoke():
    out = call("10.100.14.20")
    assert out["found"] is True
    m = out["match"]
    assert (m["cidr"], m["kind"], m["spoke"], m["env_site"]) == ("10.100.14.0/24", "spoke", "sett", "prod-eastus2")
    assert (m["vnet"], m["ip_group"], m["environment"], m["site"]) == ("vnet-sett-prod", "ipg-sett-prod", "prod", "primary")


def test_longest_prefix_wins_and_wider_range_is_listed_as_within():
    out = call("10.100.14.20")
    assert [w["cidr"] for w in out["within"]] == ["10.100.0.0/16"]
    assert out["within"][0]["kind"] == "env-site"


def test_dr_site_is_a_different_env_site():
    m = call("10.101.14.20")["match"]
    assert (m["spoke"], m["site"], m["region"], m["env_site"]) == ("sett", "dr", "centralus", "prod-centralus")


def test_known_hub_host_is_named():
    out = call("10.100.1.4")
    assert out["match"]["kind"] == "shared"
    assert out["host"] == "hubDns"


def test_address_in_env_site_but_no_spoke_matches_the_env_site():
    out = call("10.100.200.9")
    assert out["match"]["kind"] == "env-site" and out["within"] == []


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
    assert out["found"] is False and out["match"] is None
    assert len(out["covers"]) == 53
    assert "wider than every range" in out["reason"]


def test_partner_address_is_not_found():
    out = call("203.0.113.20")
    assert out["found"] is False and out["covers"] == []
    assert "not in the address plan" in out["reason"]


def test_answer_names_its_source():
    assert call("10.100.14.20")["source"] == {"file": "data/estate/address-plan.yaml", "commit": None}
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
        locate_address(None, {"address": "10.100.14.20", "spoke": "sett"}, REAL)


def test_missing_argument_is_refused():
    with pytest.raises(BadArguments):
        locate_address(None, {}, REAL)


# ---- the estate data itself

def test_duplicate_range_in_plan_is_an_estate_error():
    plan = ("ranges:\n- {cidr: 10.0.0.0/16, kind: env-site, environment: lab, site: primary, region: eastus2}\n"
            "- {cidr: 10.0.0.0/16, kind: env-site, environment: dev, site: primary, region: eastus2}\n")
    with pytest.raises(EstateError, match="duplicate"):
        call("10.0.0.1", TextSource(plan))


def test_unknown_kind_in_plan_is_an_estate_error():
    plan = "ranges:\n- {cidr: 10.0.0.0/16, kind: mystery, environment: lab, site: primary, region: eastus2}\n"
    with pytest.raises(EstateError, match="unknown kind"):
        call("10.0.0.1", TextSource(plan))


# ---- through the gateway

@pytest.fixture
def allowed_context(monkeypatch):
    import base64
    monkeypatch.setenv("WEBSITE_AUTH_ENABLED", "True")
    principal = {"auth_typ": "aad", "role_typ": "roles", "claims": [{"typ": "roles", "val": "Tools.Read"}]}
    header = base64.b64encode(json.dumps(principal).encode()).decode()

    def make(arguments):
        return json.dumps({"name": "locate_address", "arguments": arguments,
                           "transport": {"properties": {"headers": {"X-MS-CLIENT-PRINCIPAL": header}}}})
    return make


def test_gateway_passes_arguments_to_the_tool(allowed_context):
    out = json.loads(gateway.run(allowed_context({"address": "10.100.14.20"}), locate_address, source=REAL))
    assert out["match"]["spoke"] == "sett"


def test_gateway_turns_bad_arguments_into_an_answer(allowed_context):
    out = json.loads(gateway.run(allowed_context({"address": "nope"}), locate_address, source=REAL))
    assert out["error"] == "bad_arguments" and "not an IPv4" in out["reason"]


def test_gateway_hides_detail_of_unexpected_failures(allowed_context):
    out = json.loads(gateway.run(allowed_context({"address": "10.0.0.1"}), locate_address, source=TextSource("not: [valid")))
    assert out == {"error": "tool_failed"}
