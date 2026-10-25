"""resolve_env_site. Uses the real routing.yaml for known facts and small in-memory routing for edge
cases. Each test fails if the matching, the input checks or the answer's shape change."""

import json
from pathlib import Path

import pytest
import yaml

import gateway
from errors import BadArguments
from data_readers.read_addressplan_routing import ROUTING, LocalSource, NetworkDataError
from tools.resolve_env_site import resolve_env_site

REPO = Path(__file__).resolve().parents[2]
REAL = LocalSource(REPO)
ENV_SITES = yaml.safe_load((REPO / ROUTING).read_text())["env_sites"]


class RoutingSource:
    """In-memory routing for edge cases, with a fixed commit."""

    def __init__(self, routing: dict):
        self.text = yaml.safe_dump(routing)

    def read(self, path):
        assert path == ROUTING
        return self.text

    @property
    def commit(self):
        return "abc123"


def call(environment, site, source=REAL):
    return resolve_env_site(None, {"environment": environment, "site": site}, source)


def hub(env, site, region):
    """One routing entry with its hub fields."""
    return {"environment": env, "site": site, "region": region, "firewall": f"afw-{env}-{region}",
            "firewall_policy": f"afwp-{env}-{region}", "public_ip": "192.0.2.99"}


# ---- known facts from the real routing

@pytest.mark.parametrize("env_site", sorted(ENV_SITES))
def test_every_env_site_in_routing_resolves_from_its_own_environment_and_site(env_site):
    entry = ENV_SITES[env_site]
    out = call(entry["environment"], entry["site"])
    assert out["resolved"] is True and out["match"]["env_site"] == env_site
    assert (out["match"]["firewall"], out["match"]["firewall_policy"], out["match"]["firewall_public_ip"]) == \
        (entry["firewall"], entry["firewall_policy"], entry["public_ip"])
    assert out["match"]["region"] == entry["region"] and "reason" not in out and "known" not in out


def test_prod_dr_is_prod_centralus():
    # RITM0011050: prod DR only, an IP-group source and a partner destination, so no address to locate.
    out = call("prod", "dr")
    assert out["match"]["env_site"] == "prod-centralus" and out["match"]["firewall"] == "afw-hub-prod-centralus"
    assert out["source"]["files"] == [ROUTING]


def test_case_and_spaces_do_not_matter():
    assert call("  PROD ", "DR")["match"]["env_site"] == "prod-centralus"


@pytest.mark.parametrize("environment, site", [
    ("prod", "secondary"),       # a word routing does not use is never mapped
    ("prod", "prod-dr"),         # the name the drafter made up on 2026-10-25
    ("qa", "primary"),
    ("prod", "ipg-ledg-prod-dr"),  # an IP group's name is never read as a site
    ("ipg-ledg-prod-dr", "dr"),
])
def test_a_pair_routing_does_not_list_is_unresolved_with_the_pairs_it_does(environment, site):
    out = call(environment, site)
    assert out["resolved"] is False and out["match"] is None
    assert f"environment {environment!r} and site {site!r}" in out["reason"]
    assert out["known"] == [{"environment": e["environment"], "site": e["site"], "env_site": n} for n, e in ENV_SITES.items()]


def test_two_env_sites_for_one_pair_are_never_picked_between():
    source = RoutingSource({"env_sites": {"prod-eastus2": hub("prod", "dr", "eastus2"),
                                          "prod-centralus": hub("prod", "dr", "centralus")}})
    out = call("prod", "dr", source)
    assert out["resolved"] is False and out["match"] is None
    assert "2 env-sites" in out["reason"] and "prod-eastus2" in out["reason"] and "prod-centralus" in out["reason"]


def test_the_answer_names_the_commit_it_read():
    source = RoutingSource({"env_sites": {"prod-centralus": hub("prod", "dr", "centralus")}})
    assert call("prod", "dr", source)["source"] == {"files": [ROUTING], "commit": "abc123"}


def test_a_routing_entry_without_a_site_is_a_data_error():
    with pytest.raises(NetworkDataError):
        call("prod", "dr", RoutingSource({"env_sites": {"prod-centralus": {"environment": "prod"}}}))


# ---- input checks

@pytest.mark.parametrize("arguments, says", [
    ({"environment": "prod"}, "site must be a non-empty string"),
    ({"site": "dr"}, "environment must be a non-empty string"),
    ({"environment": "", "site": "dr"}, "environment must be a non-empty string"),
    ({"environment": "prod", "site": 2}, "site must be a non-empty string"),
    ({"environment": "prod", "site": "dr", "ip_group": "ipg-ledg-prod-dr"}, "only two arguments"),
    ({"env_site": "prod-dr"}, "only two arguments"),
    ("prod dr", "only two arguments"),
])
def test_bad_arguments_are_refused(arguments, says):
    with pytest.raises(BadArguments, match=says):
        resolve_env_site(None, arguments, REAL)


# ---- through the gateway

def test_gateway_passes_arguments_to_the_tool(allowed_context):
    out = json.loads(gateway.run(allowed_context({"environment": "prod", "site": "dr"}), resolve_env_site, source=REAL))
    assert out["match"]["env_site"] == "prod-centralus"


def test_gateway_turns_bad_arguments_into_an_answer(allowed_context):
    out = json.loads(gateway.run(allowed_context({"env_site": "prod-dr"}), resolve_env_site, source=REAL))
    assert out["error"] == "bad_arguments" and "only two arguments" in out["reason"]
