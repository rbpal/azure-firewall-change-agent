"""Tier 1 checks: read one env-site's `terraform show -json` plan, list what breaks the standards.

Example: `python -m policy.tier1 plan.json` prints one line per finding, such as
"caution STD-COLL-02 sett/allow-sett-app-rules/https-sett-to-googleAll: wildcard FQDN *.google.com",
and exits 2 if any finding blocks.

When it runs: CI (tier1-gate.yml) runs it on every pull request from this
repository, on the plan of each dev env-site, dev-eastus2 and dev-centralus. The
fwagent workflow does not run it on a draft yet; its draft note says so (Step 04
Task 06). No model is involved, so the same plan always gets the same answer.

Safety rule: STD-COLL-04 (open DNAT) is the only check that blocks. Every other
finding is a caution the engineer approves past with a reason. STD-COLL-07 calls
duplicate_rule_check, the agent's own tool, so the agent and the gate cannot disagree.
"""

import ipaddress
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "mcp"))

from data_readers.read_addressplan_routing import LocalSource, load_hubs, load_ranges  # noqa: E402
from errors import BadArguments  # noqa: E402
from tools.duplicate_rule_check import duplicate_rule_check  # noqa: E402

KINDS = {  # plan block -> (type word in names, priority, action)
    "nat_rule_collection": ("dnat", 1000, "Dnat"),
    "network_rule_collection": ("network", 2000, "Allow"),
    "application_rule_collection": ("app", 3000, "Allow"),
}
VAR_KEY = {"nat_rule_collection": "nat_rule_collections", "network_rule_collection": "network_rule_collections",
           "application_rule_collection": "application_rule_collections"}
GROUP_PRIORITY = 200
SPOKE = re.compile(r"^[a-z]{4}$")
RULE_KEY = re.compile(r"^(\d{3})-([a-z]+)-([a-z][a-zA-Z]*)-to-([a-z][a-zA-Z]+)$")
IP_GROUP = re.compile(r"^ipg-([a-z]{4}-(lab|dev|stage|prod)(-dr)?|partner-[a-z]+|onprem-(primary|secondary))$")
TICKET = re.compile(r"(RITM|REQ|CHG|INC)-?\d+|\d{4}-?\d{2}-?\d{2}", re.IGNORECASE)
OPEN = {"*", "0.0.0.0/0", "any", "Any"}
TOOL_TYPE = {"nat_rule_collection": "dnat", "network_rule_collection": "network",
             "application_rule_collection": "application"}
SERVICE_TAGS = frozenset(line.strip() for line in (Path(__file__).parent / "service_tags.txt").read_text().splitlines()
                         if line.strip() and not line.startswith("#"))


@dataclass(frozen=True)
class Finding:
    """One broken standard at one place in the plan."""
    level: str  # "caution" or "block"
    standard: str
    where: str
    detail: str

    def line(self) -> str:
        """The finding as one printable line."""
        return f"{self.level} {self.standard} {self.where}: {self.detail}"


# ------------------------------------------------------------ reading the plan

def load_plan(path) -> dict:
    """Read a `terraform show -json` file."""
    return json.loads(Path(path).read_text())


def _resources(plan: dict) -> list[dict]:
    """Every planned resource, from the root module and its child modules."""
    out, stack = [], [plan.get("planned_values", {}).get("root_module", {})]
    while stack:
        mod = stack.pop()
        out.extend(mod.get("resources", []))
        stack.extend(mod.get("child_modules", []))
    return out


def model(plan: dict) -> dict:
    """Turn a plan into policy name, IP groups and groups with collections and rules (keys and IP group names from the variables)."""
    res = _resources(plan)
    policies = [r["values"] for r in res if r["type"] == "azurerm_firewall_policy"]
    variables = {k: v.get("value") for k, v in plan.get("variables", {}).items()}
    groups = []
    for r in res:
        if r["type"] != "azurerm_firewall_policy_rule_collection_group":
            continue
        v = r["values"]
        var = next((x for x in variables.values() if isinstance(x, dict) and x.get("name") == v["name"]
                    and "priority" in x), {}) or {}
        cols = []
        for block, (word, _, _) in KINDS.items():
            for c in v.get(block) or []:
                var_rules = ((var.get(VAR_KEY[block]) or {}).get(c["name"]) or {}).get("rules") or {}
                by_name = {rv.get("name"): (key, rv) for key, rv in var_rules.items()}
                rules = []
                for rule in c.get("rule") or []:
                    key, rv = by_name.get(rule["name"], (None, {}))
                    rules.append({**rule, "key": key, "tfvars": rv,
                                  "source_ip_group_names": rv.get("source_ip_groups", []),
                                  "destination_ip_group_names": rv.get("destination_ip_groups", [])})
                cols.append({"block": block, "type": word, "name": c["name"], "priority": c["priority"],
                             "action": c["action"], "rules": rules})
        groups.append({"name": v["name"], "priority": v["priority"], "collections": cols})
    ip_groups = {r["values"]["name"]: r["values"].get("cidrs", []) for r in res if r["type"] == "azurerm_ip_group"}
    return {"policy": policies[0]["name"] if policies else None, "groups": groups, "ip_groups": ip_groups,
            "changes": _changes(plan)}


def _changes(plan: dict) -> dict:
    """For each rule collection group, the rule lists before and after the plan, by collection name."""
    out = {}
    for c in plan.get("resource_changes", []):
        if c.get("type") != "azurerm_firewall_policy_rule_collection_group":
            continue
        before, after = c["change"].get("before") or {}, c["change"].get("after") or {}
        name = after.get("name") or before.get("name")
        sides = {}
        for side, v in (("before", before), ("after", after)):
            sides[side] = {col["name"]: (block, col.get("rule") or [])
                           for block in KINDS for col in v.get(block) or []}
        out[name] = sides
    return out


# ------------------------------------------------------------ the checks

def check_open_dnat(m: dict, **_) -> list[Finding]:
    """STD-COLL-04: no DNAT rule may take its source from anywhere."""
    out = []
    for g, c, r in _rules(m, "nat_rule_collection"):
        if not r.get("source_addresses") and not r.get("source_ip_groups"):
            out.append(Finding("block", "STD-COLL-04", _where(g, c, r), "DNAT rule has no source"))
        for s in r.get("source_addresses") or []:
            if s in OPEN:
                out.append(Finding("block", "STD-COLL-04", _where(g, c, r), f"DNAT source {s} is open to everyone"))
    return out


def check_wildcards(m: dict, **_) -> list[Finding]:
    """STD-COLL-02: `*` or 0.0.0.0/0 anywhere, and wildcard FQDNs, are cautions (open DNAT is left to STD-COLL-04)."""
    out = []
    for g, c, r in _rules(m):
        fields = ["destination_addresses"] if c["block"] == "nat_rule_collection" else [
            "source_addresses", "destination_addresses"]
        for f in fields:
            for a in r.get(f) or []:
                if a in OPEN:
                    out.append(Finding("caution", "STD-COLL-02", _where(g, c, r), f"{f} is {a}"))
        for f in r.get("destination_fqdns") or []:
            if "*" in f:
                out.append(Finding("caution", "STD-COLL-02", _where(g, c, r), f"wildcard FQDN {f}"))
        if r.get("web_categories"):
            out.append(Finding("caution", "STD-COLL-02", _where(g, c, r), "web categories"))
    return out


def check_layout(m: dict, **_) -> list[Finding]:
    """STD-COLL-01: group priority 200, collection priority and action by type, never Deny."""
    out = []
    for g in m["groups"]:
        if g["priority"] != GROUP_PRIORITY:
            out.append(Finding("caution", "STD-COLL-01", g["name"], f"group priority {g['priority']}, expected 200"))
        for c in g["collections"]:
            _, prio, action = KINDS[c["block"]]
            if c["priority"] != prio:
                out.append(Finding("caution", "STD-COLL-01", f"{g['name']}/{c['name']}",
                                   f"collection priority {c['priority']}, expected {prio}"))
            if c["action"] != action:
                out.append(Finding("caution", "STD-COLL-01", f"{g['name']}/{c['name']}",
                                   f"action {c['action']}, expected {action}"))
    return out


def check_dnat_targets(m: dict, root: Path = REPO, **_) -> list[Finding]:
    """STD-COLL-06: DNAT goes to this site's hub public IP, translates inside this site, and each public port is used once."""
    dnat = list(_rules(m, "nat_rule_collection"))
    if not dnat:
        return []
    source = LocalSource(root)
    env_site, hub = next(((k, h) for k, h in load_hubs(source).items() if h.firewall_policy == m["policy"]), (None, None))
    if hub is None:
        return [Finding("caution", "STD-COLL-06", m["policy"] or "?", "policy is not in routing.yaml")]
    mine = [r.network for r in load_ranges(source) if r.env_site == env_site and r.kind != "env-site"]
    out, seen = [], {}
    for g, c, r in dnat:
        w = _where(g, c, r)
        if r.get("destination_address") != hub.public_ip:
            out.append(Finding("caution", "STD-COLL-06", w,
                               f"destination {r.get('destination_address')} is not this firewall's public IP {hub.public_ip}"))
        try:
            inside = any(ipaddress.ip_address(r.get("translated_address")) in n for n in mine)
        except ValueError:
            inside = False
        if not inside:
            out.append(Finding("caution", "STD-COLL-06", w,
                               f"translated address {r.get('translated_address')} is outside {env_site}"))
        for p in r.get("destination_ports") or []:
            if p in seen:
                out.append(Finding("caution", "STD-COLL-06", w, f"public port {p} already used by {seen[p]}"))
            seen.setdefault(p, r["name"])
    return out


def check_names(m: dict, **_) -> list[Finding]:
    """STD-NAME-01 to 05: group, collection, rule key and IP group names; no ticket numbers or dates."""
    out = []
    for g in m["groups"]:
        if g["name"] != "hub" and not SPOKE.match(g["name"]):
            out.append(Finding("caution", "STD-NAME-01", g["name"], "group name is not a four-letter spoke code or hub"))
        for c in g["collections"]:
            want = f"allow-{g['name']}-{c['type']}-rules"
            if c["name"] != want:
                out.append(Finding("caution", "STD-NAME-02", f"{g['name']}/{c['name']}", f"expected {want}"))
            indexes = []
            for r in c["rules"]:
                w = _where(g, c, r)
                key = r.get("key")
                hit = RULE_KEY.match(key) if key else None
                if not hit or key[4:] != r["name"]:
                    out.append(Finding("caution", "STD-NAME-03", w, f"rule key {key!r} does not follow NNN-service-src-to-dst"))
                else:
                    indexes.append(int(hit.group(1)))
                if TICKET.search(r["name"]) or (key and TICKET.search(key)):
                    out.append(Finding("caution", "STD-NAME-05", w, "rule name holds a ticket number or date"))
            if indexes and sorted(indexes) != list(range(1, len(indexes) + 1)):
                out.append(Finding("caution", "STD-NAME-03", f"{g['name']}/{c['name']}",
                                   f"indexes {sorted(indexes)} do not run from 001 with no gaps"))
    for name in m["ip_groups"]:
        if not IP_GROUP.match(name):
            out.append(Finding("caution", "STD-NAME-04", name, "IP group name does not follow STD-NAME-04 (ipg-<spoke>-<env>[-dr], ipg-partner-<partner>, ipg-onprem-primary|secondary)"))
    return out


def check_duplicates(m: dict, root: Path = REPO, **_) -> list[Finding]:
    """STD-COLL-07: ask duplicate_rule_check, the agent's own tool, whether an existing rule already allows each new rule."""
    added = _added(m)
    if not added:
        return []
    env_site = _env_site(m["policy"], root)
    if env_site is None:
        return [Finding("caution", "STD-COLL-07", m["policy"] or "?", "policy is not in routing.yaml")]
    out = []
    for g, c, r in added:
        if not r["tfvars"]:
            out.append(Finding("caution", "STD-COLL-07", _where(g, c, r), "rule is not in the tfvars, so it was not checked"))
            continue
        rule = {k: v for k, v in r["tfvars"].items() if k != "name"}
        try:
            answer = duplicate_rule_check(None, {"env_site": env_site, "type": TOOL_TYPE[c["block"]], "rule": rule},
                                          source=LocalSource(root))
        except BadArguments as exc:
            out.append(Finding("caution", "STD-COLL-07", _where(g, c, r), f"not checked: {exc}"))
            continue
        for hit in answer["matches"]:
            if hit["key"] == r["key"] and hit["file"].endswith(f"/{g['name']}.tfvars"):
                continue  # the new rule itself, already in the files of this change
            out.append(Finding("caution", "STD-COLL-07", _where(g, c, r),
                               f"{hit['relation']} by {hit['key']} in {hit['file']}"))
    return out


def check_removals(m: dict, **_) -> list[Finding]:
    """STD-COLL-08: a change may only delete rules and add new ones at the end; every other rule stays as it was, in order."""
    out = []
    for gname, sides in m["changes"].items():
        before, after = sides["before"], sides["after"]
        for cname in sorted(set(before) | set(after)):
            old = before.get(cname, (None, []))[1]
            new = after.get(cname, (None, []))[1]
            old_names, new_names = [r["name"] for r in old], [r["name"] for r in new]
            kept = [n for n in old_names if n in new_names]
            added = [n for n in new_names if n not in old_names]
            if new_names != kept + added:
                out.append(Finding("caution", "STD-COLL-08", f"{gname}/{cname}",
                                   "rules were reordered, or a new rule is not at the end"))
            old_by, new_by = {r["name"]: r for r in old}, {r["name"]: r for r in new}
            for n in kept:
                if _fields(old_by[n]) != _fields(new_by[n]):
                    out.append(Finding("caution", "STD-COLL-08", f"{gname}/{cname}/{n}", "an existing rule was changed"))
    return out


def check_service_tags(m: dict, root: Path = REPO, **_) -> list[Finding]:
    """Service tags: an address that is not an IP, range, CIDR or * must be a real Azure service tag, in this policy's region."""
    region = (_env_site(m["policy"], root) or "").split("-", 1)[-1]
    out = []
    for g, c, r in _rules(m):
        for f in ("source_addresses", "destination_addresses"):
            for a in r.get(f) or []:
                if a in OPEN or _is_address(a):
                    continue
                if a not in SERVICE_TAGS:
                    out.append(Finding("caution", "SERVICE-TAG", _where(g, c, r), f"{a} is not an Azure service tag"))
                elif "." in a and a.split(".", 1)[1].lower() != region:
                    out.append(Finding("caution", "SERVICE-TAG", _where(g, c, r),
                                       f"{a} is for another region; this policy is in {region}"))
    return out


CHECKS = [check_open_dnat, check_wildcards, check_layout, check_dnat_targets, check_names,
          check_duplicates, check_removals, check_service_tags]


def run(plan: dict, root: Path = REPO) -> list[Finding]:
    """Run every Tier 1 check on one plan and return all findings, blocks first."""
    m = model(plan)
    findings = [f for check in CHECKS for f in check(m, root=root)]
    return sorted(findings, key=lambda f: (f.level != "block", f.standard, f.where))


# ------------------------------------------------------------ helpers

def _rules(m: dict, block: str | None = None):
    """Yield (group, collection, rule) for every rule, or only those in one kind of collection."""
    for g in m["groups"]:
        for c in g["collections"]:
            if block is None or c["block"] == block:
                for r in c["rules"]:
                    yield g, c, r


def _added(m: dict) -> list:
    """(group, collection, rule) for each rule this plan adds: in the after list of its collection, not in the before list."""
    out = []
    for g, c, r in _rules(m):
        sides = m["changes"].get(g["name"])
        if sides is None:
            continue
        before_names = {x["name"] for x in sides["before"].get(c["name"], (None, []))[1]}
        if r["name"] not in before_names:
            out.append((g, c, r))
    return out


def _env_site(policy: str | None, root: Path) -> str | None:
    """The env-site whose hub uses this policy, from routing.yaml."""
    return next((k for k, h in load_hubs(LocalSource(root)).items() if h.firewall_policy == policy), None)


def _fields(rule: dict) -> dict:
    """A rule's fields that matter for traffic, for before-and-after comparison."""
    return {k: v for k, v in rule.items() if k not in ("description",)}


def _is_address(text: str) -> bool:
    """True for an IPv4 address, CIDR or a-b range."""
    try:
        for part in text.split("-"):
            ipaddress.ip_network(part.strip(), strict=False)
        return True
    except ValueError:
        return False


def _where(g: dict, c: dict, r: dict) -> str:
    """Name the place of a rule as group/collection/rule."""
    return f"{g['name']}/{c['name']}/{r['name']}"


def main(argv: list[str]) -> int:
    """Print the findings for one plan file; exit 2 if any blocks, else 0."""
    findings = run(load_plan(argv[1]))
    for f in findings:
        print(f.line())
    print(f"{len(findings)} findings, {sum(f.level == 'block' for f in findings)} blocking")
    return 2 if any(f.level == "block" for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
