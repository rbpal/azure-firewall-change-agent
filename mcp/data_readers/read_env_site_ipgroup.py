"""Read the firewall rules and IP groups that are in main.

The duplicate rule tool uses this to compare a new rule with the rules
that already exist. It is a helper, not a tool. The agent never calls it directly.

It reads every rules file of one env-site, the hub file included.
The list of files comes from routing.yaml, never from the caller.
A rule can name an IP group, so it also reads the IP groups and their addresses.
"""

import hcl2
from hcl2.utils import SerializationOptions

from data_readers.read_addressplan_routing import NetworkDataError, Source, load_hubs

HUB = "hub"
RULES_FILE = "infra/envs/{env_site}/firewall_policy_rule_collection_groups/{name}.tfvars"
IP_GROUPS_FILE = "infra/envs/{env_site}/ip-groups.tfvars"
# Azure Firewall applies DNAT rules first, then network rules, then application rules.
COLLECTION_TYPES = {
    "nat_rule_collections": "dnat",
    "network_rule_collections": "network",
    "application_rule_collections": "application",
}
ORDER = list(COLLECTION_TYPES.values())
HCL_OPTIONS = SerializationOptions(with_comments=False, strip_string_quotes=True)


def load_hcl(text: str, name: str, path: str) -> dict:
    """Parse a tfvars file that must hold exactly one variable, and return that variable."""
    try:
        data = hcl2.loads(text, serialization_options=HCL_OPTIONS)
    except Exception as exc:
        raise NetworkDataError(f"{path} is not valid HCL: {exc}") from exc
    if set(data) != {name}:
        raise NetworkDataError(f"{path} must hold one variable named {name!r}, found {sorted(data)}")
    return data[name]


def parse_rules(text: str, name: str, path: str) -> dict:
    """Parse one rules file and list its collections and rules in the order Azure applies them."""
    group = load_hcl(text, name, path)
    collections = []
    for key, value in group.items():
        if not key.endswith("_rule_collections"):
            continue
        kind = COLLECTION_TYPES.get(key)
        if kind is None:
            raise NetworkDataError(f"{path} has an unknown collection type {key!r}")
        for collection, c in value.items():
            rules = [{"key": k, **fields} for k, fields in sorted((c.get("rules") or {}).items())]
            collections.append({"type": kind, "name": collection, "priority": c.get("priority"),
                                "action": c.get("action"), "rules": rules})
    collections.sort(key=lambda c: (ORDER.index(c["type"]), c["priority"] or 0))
    return {"file": path, "rule_collection_group": group.get("name"), "priority": group.get("priority"),
            "collections": collections}


def read_env_site(source: Source, env_site: str) -> list[dict]:
    """Read every rules file of one env-site, hub included, sorted by group priority then name."""
    hubs = load_hubs(source)
    if env_site not in hubs:
        raise NetworkDataError(f"env-site {env_site} is not in routing")
    names = sorted(hubs[env_site].spokes) + [HUB]
    groups = []
    for name in names:
        path = RULES_FILE.format(env_site=env_site, name=name)
        groups.append(parse_rules(source.read(path), name, path))
    return sorted(groups, key=lambda g: (g["priority"] or 0, g["rule_collection_group"] or ""))


def read_ip_groups(source: Source, env_site: str) -> dict[str, list[str]]:
    """Read one env-site's IP groups as a map of group name to its CIDRs."""
    path = IP_GROUPS_FILE.format(env_site=env_site)
    groups = load_hcl(source.read(path), "ip_groups", path)
    try:
        return {g["name"]: list(g["cidrs"]) for g in groups.values()}
    except (KeyError, TypeError) as exc:
        raise NetworkDataError(f"{path} has an IP group without a name or cidrs: {exc}") from exc
