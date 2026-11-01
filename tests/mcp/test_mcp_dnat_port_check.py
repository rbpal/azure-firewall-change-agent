"""dnat_port_check and the overlap test Tier 1 shares. Uses the real rules for known facts
(prod-eastus2 publishes TCP 2221 and 2223; stage has no DNAT rules) and small in-memory rules
files for edge cases. Each test fails if the conflict criteria, the coverage handling or the
answer's shape change."""

from pathlib import Path

import pytest

from errors import BadArguments
from data_readers.read_addressplan_routing import LocalSource, NetworkDataError
from tools.dnat_port_check import dnat_port_check

REPO = Path(__file__).resolve().parents[2]
REAL = LocalSource(REPO)
RULES = "infra/envs/{env_site}/firewall_policy_rule_collection_groups/{name}.tfvars"


class OverrideSource:
    """The real repo, with some files replaced by in-memory text or made unreadable."""

    def __init__(self, files: dict[str, str] | None = None, broken: set[str] = frozenset(), commit: str = "abc123"):
        self.files, self.broken, self.commit = files or {}, broken, commit

    def read(self, path):
        if path in self.broken:
            raise NetworkDataError(f"{path} is not in the snapshot container")
        return self.files[path] if path in self.files else REAL.read(path)


def dnat_file(env_site: str, name: str, rules: str) -> OverrideSource:
    """Replace one rules file with a single DNAT collection holding the given rules."""
    text = f"""
{name} = {{
  name     = "{name}"
  priority = 200
  nat_rule_collections = {{
    allow-{name}-dnat-rules = {{
      name     = "allow-{name}-dnat-rules"
      priority = 1000
      action   = "Dnat"
      rules = {{
{rules}
      }}
    }}
  }}
}}
"""
    return OverrideSource({RULES.format(env_site=env_site, name=name): text})


def rule(key="001-sftp-partner-to-xferSftp", protocols='["TCP"]', destination='"192.0.2.12"', ports='["22"]',
         source='["198.51.100.16/28"]') -> str:
    """One DNAT rule in tfvars form; the default publishes TCP 22 on the stage-eastus2 firewall."""
    return f"""
        {key} = {{
          protocols           = {protocols}
          source_addresses    = {source}
          destination_address = {destination}
          destination_ports   = {ports}
          translated_address  = "10.102.20.14"
          translated_port     = "22"
        }}"""


def check(env_site, ports, protocols=("TCP",), source=REAL):
    """Call the tool the way the gateway does."""
    return dnat_port_check(None, {"env_site": env_site, "protocols": list(protocols), "destination_ports": ports}, source)


# ---------------------------------------------------------------- free ports (real data)

def test_port_22_is_free_on_both_stage_firewalls_as_ritm0011020_needs():
    for env_site, ip in (("stage-eastus2", "192.0.2.12"), ("stage-centralus", "192.0.2.13")):
        out = check(env_site, ["22"])
        assert out["status"] == "no_conflicts" and out["conflicts"] == [] and out["inconclusive"] == []
        assert out["firewall_public_ip"] == ip


def test_a_port_between_two_published_ports_is_free():
    out = check("prod-eastus2", ["2222"])
    assert out["status"] == "no_conflicts"
    assert out["dnat_rules_read"] == 2


def test_every_rules_file_of_the_policy_is_read_hub_included():
    out = check("stage-eastus2", ["22"])
    names = sorted(Path(f).stem for f in out["source"]["files"])
    assert names == ["hub", "ledg", "port", "rprt", "sett", "xfer"]
    assert "6 rules files of afwp-hub-stage-eastus2" in out["coverage"]


# ---------------------------------------------------------------- conflicting ports (real data)

def test_a_published_port_names_the_rule_that_holds_it():
    out = check("prod-eastus2", ["2221"])
    assert out["status"] == "conflicts_found"
    [c] = out["conflicts"]
    assert c["key"] == "001-sftp-woodgrove-to-xferSftp" and c["overlapping_ports"] == ["2221"]
    assert c["destination_address"] == "192.0.2.10" and c["protocols"] == ["TCP"]
    assert c["file"].endswith("prod-eastus2/firewall_policy_rule_collection_groups/xfer.tfvars")
    assert c["translated_address"] == "10.100.20.14"


def test_a_requested_range_lists_each_rule_it_overlaps():
    out = check("prod-eastus2", ["2220-2224"])
    assert [(c["key"], c["overlapping_ports"]) for c in out["conflicts"]] == [
        ("001-sftp-woodgrove-to-xferSftp", ["2221"]), ("002-sftp-litware-to-xferSftp", ["2223"])]


def test_an_existing_udp_rule_on_the_same_port_neither_blocks_nor_clouds_a_tcp_request():
    source = dnat_file("stage-eastus2", "xfer", rule(protocols='["UDP"]'))
    out = check("stage-eastus2", ["22"], source=source)
    assert out["status"] == "no_conflicts" and out["conflicts"] == [] and out["inconclusive"] == []
    assert out["dnat_rules_read"] == 1


# ---------------------------------------------------------------- primary and DR differ

def test_primary_and_dr_are_answered_from_their_own_policy():
    assert check("prod-eastus2", ["2221"])["status"] == "conflicts_found"
    assert check("prod-centralus", ["2221"])["status"] == "no_conflicts"


def test_a_port_taken_only_at_dr_conflicts_at_dr_and_stays_free_at_primary():
    source = dnat_file("stage-centralus", "xfer", rule(destination='"192.0.2.13"'))
    assert check("stage-eastus2", ["22"], source=source)["status"] == "no_conflicts"
    dr = check("stage-centralus", ["22"], source=source)
    assert dr["status"] == "conflicts_found" and dr["firewall_public_ip"] == "192.0.2.13"


# ---------------------------------------------------------------- the conflict criteria

def test_a_different_source_still_conflicts_because_the_port_is_once_per_firewall():
    source = dnat_file("stage-eastus2", "xfer", rule(source='["203.0.113.200/29"]'))
    assert check("stage-eastus2", ["22"], source=source)["status"] == "conflicts_found"


def test_a_rule_for_tcp_and_udp_conflicts_with_a_tcp_request():
    source = dnat_file("stage-eastus2", "xfer", rule(protocols='["TCP", "UDP"]'))
    assert check("stage-eastus2", ["22"], source=source)["status"] == "conflicts_found"


@pytest.mark.parametrize("ports, conflict", [('["20-25"]', True), ('["23-30"]', False), ('["21", "22"]', True)])
def test_numeric_port_ranges_are_compared_not_their_text(ports, conflict):
    source = dnat_file("stage-eastus2", "xfer", rule(ports=ports))
    assert (check("stage-eastus2", ["22"], source=source)["status"] == "conflicts_found") is conflict


def test_a_hub_dnat_rule_counts():
    source = dnat_file("stage-eastus2", "hub", rule())
    out = check("stage-eastus2", ["22"], source=source)
    assert out["status"] == "conflicts_found" and out["conflicts"][0]["file"].endswith("/hub.tfvars")


def test_a_network_rule_on_the_same_port_is_not_a_published_port():
    text = """
xfer = {
  name     = "xfer"
  priority = 200
  network_rule_collections = {
    allow-xfer-network-rules = {
      name = "allow-xfer-network-rules"
      priority = 2000
      action = "Allow"
      rules = {
        001-ssh-xfer-to-partner = {
          protocols = ["TCP"]
          source_addresses = ["10.102.20.0/24"]
          destination_addresses = ["198.51.100.16/28"]
          destination_ports = ["22"]
        }
      }
    }
  }
}
"""
    source = OverrideSource({RULES.format(env_site="stage-eastus2", name="xfer"): text})
    assert check("stage-eastus2", ["22"], source=source)["status"] == "no_conflicts"


# ---------------------------------------------------------------- incomplete coverage returns uncertainty

def test_an_unreadable_rules_file_makes_the_answer_inconclusive_not_free():
    source = OverrideSource(broken={RULES.format(env_site="stage-eastus2", name="sett")})
    out = check("stage-eastus2", ["22"], source=source)
    assert out["status"] == "inconclusive"
    assert out["inconclusive"] == [{"code": "rules_file_unreadable",
                                    "file": RULES.format(env_site="stage-eastus2", name="sett"),
                                    "detail": RULES.format(env_site="stage-eastus2", name="sett")
                                    + " is not in the snapshot container"}]


def test_a_conflict_is_still_reported_when_another_file_is_unreadable():
    source = OverrideSource(broken={RULES.format(env_site="prod-eastus2", name="hub")})
    out = check("prod-eastus2", ["2221"], source=source)
    assert out["status"] == "conflicts_found" and out["inconclusive"][0]["code"] == "rules_file_unreadable"


@pytest.mark.parametrize("destination, conflict", [('"203.0.113.9"', False), ('"192.0.2.13"', False),
                                                  ('"192.0.2.12/31"', True), ('"*"', True)],
                         ids=["another public IP", "the DR firewall's IP", "a range holding this IP", "any address"])
def test_destination_ips_must_overlap_to_conflict(destination, conflict):
    source = dnat_file("stage-eastus2", "xfer", rule(destination=destination))
    out = check("stage-eastus2", ["22"], source=source)
    assert out["status"] == ("conflicts_found" if conflict else "no_conflicts")


@pytest.mark.parametrize("protocols, ports, destination", [('["ICMP"]', '["22"]', '"192.0.2.12"'),
                                                           ('[]', '["22"]', '"192.0.2.12"'),
                                                           ('["TCP"]', '["ssh"]', '"192.0.2.12"'),
                                                           ('["TCP"]', '["22"]', '"not-an-ip"')])
def test_an_existing_rule_that_cannot_be_read_is_inconclusive(protocols, ports, destination):
    source = dnat_file("stage-eastus2", "xfer", rule(protocols=protocols, ports=ports, destination=destination))
    out = check("stage-eastus2", ["22"], source=source)
    assert out["status"] == "inconclusive" and out["inconclusive"][0]["code"] == "rule_unreadable"


# ---------------------------------------------------------------- arguments and stamp

@pytest.mark.parametrize("arguments, message", [
    ({"env_site": "prod-dr", "protocols": ["TCP"], "destination_ports": ["22"]}, "env_site must be one of"),
    ({"env_site": "stage-eastus2", "protocols": ["UDP"], "destination_ports": ["22"]}, "TCP only"),
    ({"env_site": "stage-eastus2", "protocols": ["Any"], "destination_ports": ["22"]}, "TCP only"),
    ({"env_site": "stage-eastus2", "protocols": [], "destination_ports": ["22"]}, "non-empty list"),
    ({"env_site": "stage-eastus2", "protocols": ["TCP"], "destination_ports": ["64000"]}, "1-63999"),
    ({"env_site": "stage-eastus2", "protocols": ["TCP"], "destination_ports": ["ssh"]}, "not a port"),
    ({"env_site": "stage-eastus2", "protocols": ["TCP"], "destination_ports": []}, "destination_ports must be"),
    ({"env_site": "stage-eastus2", "protocols": ["TCP"], "destination_ports": ["22"], "source": "x"}, "only three"),
])
def test_bad_arguments_are_refused_with_a_reason(arguments, message):
    with pytest.raises(BadArguments, match=message):
        dnat_port_check(None, arguments, REAL)


def test_the_answer_names_the_commit_it_read():
    out = check("stage-eastus2", ["22"], source=OverrideSource(commit="80a67de"))
    assert out["source"]["commit"] == "80a67de" and "commit 80a67de" in out["coverage"]
