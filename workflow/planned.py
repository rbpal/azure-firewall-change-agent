"""Planned addresses: check the engineer's record of a subnet that does not exist yet, and list what it still needs.

Example: the engineer accepts 10.104.40.0/24 as a planned subnet with
`{cidr: 10.104.40.0/24, environment: dev, site: primary,
firewall_policy: afwp-hub-dev-eastus2, spoke: pymt, placement: sett}`. `spoke` is
the planned subnet's own spoke code, used in rule names; `placement` is the spoke
whose file takes the rule. The rule goes in the existing sett file, so nothing is
missing and the agent drafts. With
`placement: pymt`, no pymt spoke exists at dev-eastus2, so the workflow lists the
rules file, variable, main.tf entry and network-data entries the platform team
must add first, and the ticket waits.

Why: preparing firewall policy before a spoke is built can be valid, but only the
engineer knows the planned CIDR, site, policy and placement. The record makes that
knowledge explicit and auditable instead of a guess by the agent.

Safety rule: the record can only describe an address the ticket already names, at
a site the ticket selects, on that site's real policy. It never adds an address or
a site. The workflow writes rules files only; it never writes Terraform code, so a
missing spoke is listed, not created.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path

import yaml

ROUTING = "data/network/routing.yaml"
ADDRESS_PLAN = "data/network/address-plan.yaml"
FIELDS = {"cidr", "environment", "site", "firewall_policy", "spoke", "placement"}
SPOKE = re.compile(r"^[a-z]{4}$")
REGION = {"primary": "eastus2", "dr": "centralus"}


def _ticket_cidrs(ticket: dict) -> set[str]:
    """Every CIDR written on the ticket, on either side."""
    return {a["cidr"] for side in ("sources", "destination") for a in ticket.get(side) or [] if "cidr" in a}


def check_planned(repo: Path, ticket: dict, planned: list) -> list[str]:
    """Every way the planned-address record fails to describe the ticket's own addresses, sites and policies."""
    if not isinstance(planned, list):
        return ["the planned-address file must hold a list of entries"]
    sites = yaml.safe_load((Path(repo) / ROUTING).read_text())["env_sites"]
    selected = {(env, site) for env, chosen in ticket["change_sites"].items() for site in chosen}
    errors = []
    for i, entry in enumerate(planned):
        if not isinstance(entry, dict) or set(entry) != FIELDS:
            errors.append(f"entry {i}: needs exactly {', '.join(sorted(FIELDS))}")
            continue
        try:
            ipaddress.IPv4Network(entry["cidr"], strict=True)
        except ValueError as e:
            errors.append(f"entry {i}: {entry['cidr']} is not a valid network ({e})")
            continue
        if entry["cidr"] not in _ticket_cidrs(ticket):
            errors.append(f"entry {i}: {entry['cidr']} is not on the ticket; acceptance cannot add an address")
        if (entry["environment"], entry["site"]) not in selected:
            errors.append(f"entry {i}: {entry['environment']} {entry['site']} is not a site the ticket selects")
            continue
        env_site = f"{entry['environment']}-{REGION.get(entry['site'], '?')}"
        policy = (sites.get(env_site) or {}).get("firewall_policy")
        if entry["firewall_policy"] != policy:
            errors.append(f"entry {i}: {env_site} uses policy {policy}, not {entry['firewall_policy']}")
        for key in ("spoke", "placement"):
            if not SPOKE.match(str(entry[key])):
                errors.append(f"entry {i}: {key} {entry[key]!r} is not a four-letter spoke name")
    return errors


def _text(path: Path) -> str:
    """A file's text, or '' when the file does not exist (some demo env-sites hold rules files only)."""
    return path.read_text() if path.exists() else ""


def missing_spoke_files(repo: Path, ticket: dict, planned: list) -> list[str]:
    """What must exist before a rule can go in each planned entry's placement spoke; empty when it all exists."""
    repo = Path(repo)
    sites = yaml.safe_load((repo / ROUTING).read_text())["env_sites"]
    plan = yaml.safe_load((repo / ADDRESS_PLAN).read_text())["ranges"]
    groups = {a["ip_group"] for side in ("sources", "destination") for a in ticket.get(side) or [] if "ip_group" in a}
    out = []
    for entry in planned:
        spoke, env_site = entry["placement"], f"{entry['environment']}-{REGION[entry['site']]}"
        folder = f"infra/envs/{env_site}"
        rules = f"{folder}/firewall_policy_rule_collection_groups/{spoke}.tfvars"
        if (repo / rules).exists() and spoke in ((sites.get(env_site) or {}).get("spokes") or {}):
            continue  # an existing spoke takes the rule; a planned destination needs nothing new
        if not (repo / rules).exists():
            out.append(f"{rules}: the rule collection group for spoke {spoke}")
        if not re.search(rf'^variable "{spoke}"', _text(repo / folder / "variables.tf"), re.M):
            out.append(f'{folder}/variables.tf: variable "{spoke}"')
        if not re.search(rf"^\s*{spoke}\s*=\s*var\.{spoke}\b", _text(repo / folder / "main.tf"), re.M):
            out.append(f"{folder}/main.tf: {spoke} = var.{spoke} in the rules map")
        if spoke not in ((sites.get(env_site) or {}).get("spokes") or {}):
            out.append(f"{ROUTING}: env_sites.{env_site}.spokes.{spoke}")
        if not any(r["cidr"] == entry["cidr"] and r.get("spoke") == spoke for r in plan):
            out.append(f"{ADDRESS_PLAN}: range {entry['cidr']} for spoke {spoke} at {env_site}")
        group = f"ipg-{spoke}-{entry['environment']}" + ("-dr" if entry["site"] == "dr" else "")
        if group in groups and f"{group} = {{" not in _text(repo / folder / "ip-groups.tfvars"):
            out.append(f"{folder}/ip-groups.tfvars: {group}")
    return out
