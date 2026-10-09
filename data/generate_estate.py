"""Generate the synthetic firewall estate. All names and addresses are fictional.

Writes the clean pattern only: one rule collection group per spoke plus `hub`
in each of the eight firewall policies, fixed priorities, no Deny rules, and
DR mirroring primary wherever the DR spoke exists. Legacy quirks belong in the
eval set as deliberate bad inputs, never here.

The output is the same on every run, so the estate never shifts under the eval.

Usage:
    uv run python data/generate_estate.py            # writes into the repo
    uv run python data/generate_estate.py --out DIR  # writes somewhere else
"""

from __future__ import annotations

import argparse
import random
import re
from pathlib import Path

import yaml

SEED = 20261008
REPO = Path(__file__).resolve().parent.parent

# Second octet of the primary site; the DR site is the next number.
ENVS = {"prod": 100, "stage": 102, "dev": 104, "lab": 106}
SITES = {"primary": "eastus2", "dr": "centralus"}

SPOKES = {  # code: (third octet, what it holds)
    "sett": (14, "Settlement app servers"),
    "rprt": (15, "Reporting batch servers"),
    "ledg": (16, "Ledger databases"),
    "port": (17, "Client portal web front ends"),
    "xfer": (20, "SFTP and partner file transfer"),
}
NO_DR = {("lab", "port"), ("dev", "port"), ("lab", "rprt")}  # built in East US 2 only

SHARED_OCTET = 1  # hub shared services at each site
SHARED_HOSTS = {"hubDns": [4, 5], "hubNtp": [6], "hubDc": [7], "hubSyslog": [8]}
SFTP_HOST = 14  # 10.<x>.20.14, the DNAT target

PARTNERS = [  # name, code, /28 from the RFC 5737 documentation ranges
    ("Northwind Traders", "northwind", "203.0.113.16/28"),
    ("Fabrikam", "fabrikam", "203.0.113.32/28"),
    ("Woodgrove Bank", "woodgrove", "203.0.113.48/28"),
    ("Litware", "litware", "203.0.113.64/28"),
    ("Fourth Coffee", "fourthcoffee", "203.0.113.80/28"),
    ("Tailspin", "tailspin", "198.51.100.16/28"),
    ("Proseware", "proseware", "198.51.100.32/28"),
    ("Lamna Healthcare", "lamna", "198.51.100.48/28"),
    ("Adventure Works", "adventureworks", "198.51.100.64/28"),
    ("Wingtip Toys", "wingtip", "198.51.100.80/28"),
]
PARTNER_SERVICES = {"Fs": "https", "Sftp": "sftp", "Smtp": "smtp", "Mq": "amqps"}

SERVICES = {  # name: (protocols, ports)
    "https": (["TCP"], ["443"]),
    "sftp": (["TCP"], ["22"]),
    "sql": (["TCP"], ["1433"]),
    "smtp": (["TCP"], ["587"]),
    "amqps": (["TCP"], ["5671"]),
    "dns": (["TCP", "UDP"], ["53"]),
    "ntp": (["UDP"], ["123"]),
    "ldaps": (["TCP"], ["636"]),
    "syslog": (["UDP"], ["514"]),
}

# Network rules per spoke and environment. sett in prod holds 23, so the next
# sett rule there is 024, the index the plan's worked example uses.
NETWORK_COUNTS = {
    "sett": {"lab": 18, "dev": 20, "stage": 22, "prod": 23},
    "rprt": {"lab": 5, "dev": 6, "stage": 6, "prod": 6},
    "ledg": {"lab": 8, "dev": 8, "stage": 9, "prod": 9},
    "port": {"lab": 4, "dev": 4, "stage": 5, "prod": 5},
    "xfer": {"lab": 8, "dev": 8, "stage": 7, "prod": 6},
}
# Internal flows go only to spokes that exist at every site.
INTERNAL_FLOWS = {
    "sett": [("sql", "ledg", "Sql"), ("sftp", "xfer", "Sftp")],
    "rprt": [("sql", "ledg", "Sql"), ("https", "sett", "Api"), ("sftp", "xfer", "Sftp")],
    "ledg": [],
    "port": [("https", "sett", "Api"), ("sql", "ledg", "Sql")],
    "xfer": [("https", "sett", "Api")],
}
# Flows that must NOT exist, because a sample ticket asks for them.
EXCLUDED = {("sett", "https", "northwindFs")}  # RITM0010042

APP_RULES = {  # spoke: [(partner code)], https to api.<code>.example
    "sett": ["northwind", "woodgrove"],  # 001 is removed by RITM0010044 in dev
    "rprt": ["litware"],
    "port": ["fabrikam", "tailspin"],
}
# DNAT exists in prod primary only. Public port 2222 stays free for RITM0010043.
DNAT_RULES = [("woodgrove", "2221"), ("litware", "2223")]


# ---------------------------------------------------------------- the model


def env_sites():
    """The eight env-sites, in a fixed order."""
    out = []
    for i, (env, octet) in enumerate(ENVS.items()):
        for j, (site, region) in enumerate(SITES.items()):
            out.append({
                "name": f"{env}-{region}",
                "environment": env,
                "site": site,
                "region": region,
                "octet": octet + j,
                "suffix": "-dr" if site == "dr" else "",
                "public_ip": f"192.0.2.{10 + 2 * i + j}",
            })
    return out


def spoke_exists(env, site, spoke):
    return site == "primary" or (env, spoke) not in NO_DR


def cidr(es, third, host=None):
    return f"10.{es['octet']}.{third}.{host}/32" if host is not None else f"10.{es['octet']}.{third}.0/24"


def ip_group(spoke, es):
    return f"ipg-{spoke}-{es['environment']}{es['suffix']}"


def flow_catalog():
    """Every spoke's network flows in a fixed shuffled order. An environment
    takes the first N, so a flow keeps the same index in every env-site."""
    catalog = {}
    for spoke in SPOKES:
        rng = random.Random(f"{SEED}-{spoke}")
        flows = [(svc, dst, f"{dst}{tok}") for svc, dst, tok in INTERNAL_FLOWS[spoke]]
        flows += [(svc, code, f"{code}{tok}") for _, code, _ in PARTNERS for tok, svc in PARTNER_SERVICES.items()]
        flows = [f for f in flows if (spoke, f[0], f[2]) not in EXCLUDED]
        rng.shuffle(flows)
        # Decide once per flow whether the source is an IP group, so DR matches primary.
        catalog[spoke] = [(svc, dst, token, rng.random() < 0.25) for svc, dst, token in flows]
    return catalog


def build_estate():
    """The whole estate as plain data. Rendering to files comes after."""
    catalog = flow_catalog()
    partners = {code: cidr_ for _, code, cidr_ in PARTNERS}

    policies = {}
    for es in env_sites():
        env, site = es["environment"], es["site"]
        groups = {}
        spokes_here = [s for s in SPOKES if spoke_exists(env, site, s)]

        for spoke in spokes_here:
            third = SPOKES[spoke][0]
            network = []
            for svc, dst, token, use_group in catalog[spoke][: NETWORK_COUNTS[spoke][env]]:
                protocols, ports = SERVICES[svc]
                rule = {"name": f"{svc}-{spoke}-to-{token}", "protocols": protocols}
                if use_group:
                    rule["source_ip_groups"] = [ip_group(spoke, es)]
                else:
                    rule["source_addresses"] = [cidr(es, third)]
                rule["destination_addresses"] = [partners.get(dst) or cidr(es, SPOKES[dst][0])]
                rule["destination_ports"] = ports
                network.append(rule)

            app = []
            for code in APP_RULES.get(spoke, []):
                name = f"https-{spoke}-to-{code}Api"
                app.append({
                    "name": name,
                    "protocols": ["Https:443"],
                    "source_ip_groups": [ip_group(spoke, es)],
                    "destination_fqdns": [f"api.{code}.example"],
                })

            dnat = []
            if spoke == "xfer" and es["name"] == "prod-eastus2":
                for code, public_port in DNAT_RULES:
                    name = f"sftp-{code}-to-xferSftp"
                    dnat.append({
                        "name": name,
                        "protocols": ["TCP"],
                        "source_addresses": [partners[code]],
                        "destination_address": es["public_ip"],
                        "destination_ports": [public_port],
                        "translated_address": f"10.{es['octet']}.{third}.{SFTP_HOST}",
                        "translated_port": "22",
                    })
            groups[spoke] = {"dnat": dnat, "network": network, "app": app}

        hub_sources = [cidr(es, SPOKES[s][0]) for s in sorted(spokes_here, key=lambda s: SPOKES[s][0])]
        hub = []
        for svc, token in [("dns", "hubDns"), ("ntp", "hubNtp"), ("ldaps", "hubDc"), ("syslog", "hubSyslog")]:
            protocols, ports = SERVICES[svc]
            name = f"{svc}-spokes-to-{token}"
            hub.append({
                "name": name,
                "protocols": protocols,
                "source_addresses": hub_sources,
                "destination_addresses": [cidr(es, SHARED_OCTET, h) for h in SHARED_HOSTS[token]],
                "destination_ports": ports,
            })
        groups["hub"] = {"dnat": [], "network": hub, "app": []}
        policies[es["name"]] = {"env_site": es, "groups": groups}
    return policies


# ---------------------------------------------------------------- rendering

IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
BLANK = object()


class Obj(list):
    """An HCL object as ordered (key, value) pairs, which may include BLANK."""


def hcl_scalar(v):
    if isinstance(v, list):
        return "[" + ", ".join(hcl_scalar(x) for x in v) + "]"
    if isinstance(v, int):
        return str(v)
    return '"' + str(v).replace("\\", "\\\\").replace('"', '\\"') + '"'


def hcl_object(items, indent):
    """items: (key, value) pairs or BLANK. A dict value is a nested object.
    Consecutive one-line attributes align their `=`, as `terraform fmt` does."""
    pad = "  " * indent
    lines, run = [], []

    def flush():
        width = max((len(k) for k, _ in run), default=0)
        lines.extend(f"{pad}{k.ljust(width)} = {v}" for k, v in run)
        run.clear()

    for item in items:
        if item is BLANK:
            flush()
            lines.append("")
            continue
        key, value = item
        key = key if IDENT.match(key) else f'"{key}"'
        if isinstance(value, (dict, Obj)):
            flush()
            lines.append(f"{pad}{key} = {{")
            lines.extend(hcl_object(value if isinstance(value, Obj) else list(value.items()), indent + 1))
            lines.append(f"{pad}}}")
        else:
            run.append((key, hcl_scalar(value)))
    flush()
    return lines


def collection(kind, spoke, rules):
    priority, action = {"dnat": (1000, "Dnat"), "network": (2000, "Allow"), "app": (3000, "Allow")}[kind]
    name = f"allow-{spoke}-{'app' if kind == 'app' else kind}-rules"
    keyed = {f"{i:03d}-{r['name']}": r for i, r in enumerate(rules, start=1)}
    return name, {"name": name, "priority": priority, "action": action, "rules": keyed}


def render_group(spoke, group):
    items = [("name", spoke), ("firewall_policy_key", "firewall_policy"), ("priority", 200)]
    for kind, attr in [("dnat", "nat_rule_collections"), ("network", "network_rule_collections"),
                       ("app", "application_rule_collections")]:
        if group[kind]:  # a group leaves out a collection it has no rules for
            name, body = collection(kind, spoke, group[kind])
            items += [BLANK, (attr, {name: body})]
    body = "\n".join(hcl_object([(spoke, Obj(items))], 0))
    return "# Synthetic estate. All names and addresses are fictional.\n" + body + "\n"


def render_ip_groups(es):
    groups = {
        ip_group(s, es): {"name": ip_group(s, es), "cidrs": [cidr(es, SPOKES[s][0])]}
        for s in SPOKES if spoke_exists(es["environment"], es["site"], s)
    }
    body = "\n".join(hcl_object([("ip_groups", groups)], 0))
    return "# Synthetic estate. All names and addresses are fictional.\n" + body + "\n"


def address_plan():
    ranges = []
    for es in env_sites():
        base = {"environment": es["environment"], "site": es["site"], "region": es["region"]}
        ranges.append({"cidr": f"10.{es['octet']}.0.0/16", **base, "kind": "env-site"})
        ranges.append({
            "cidr": cidr(es, SHARED_OCTET), **base, "kind": "shared",
            "holds": "Hub shared services",
            "hosts": {t: [f"10.{es['octet']}.{SHARED_OCTET}.{h}" for h in hs] for t, hs in SHARED_HOSTS.items()},
        })
        for spoke, (third, holds) in SPOKES.items():
            if spoke_exists(es["environment"], es["site"], spoke):
                ranges.append({
                    "cidr": cidr(es, third), **base, "kind": "spoke", "spoke": spoke, "holds": holds,
                    "vnet": f"vnet-{spoke}-{es['environment']}{es['suffix']}", "ip_group": ip_group(spoke, es),
                })
    return {"ranges": ranges}


def routing():
    out = {}
    for es in env_sites():
        fw = f"afw-hub-{es['name']}"
        out[es["name"]] = {
            "environment": es["environment"], "site": es["site"], "region": es["region"],
            "hub": f"vhub-{es['name']}", "firewall": fw, "firewall_policy": f"afwp-hub-{es['name']}",
            "public_ip": es["public_ip"],
            # Routing intent: internet and private traffic from every spoke passes the hub firewall.
            "spokes": {
                s: {"cidr": cidr(es, SPOKES[s][0]), "next_hop": fw, "for": ["internet", "private"]}
                for s in SPOKES if spoke_exists(es["environment"], es["site"], s)
            },
        }
    return {"env_sites": out}


def partners_file():
    return {"partners": [
        {"name": name, "code": code, "cidr": c, "fqdn": f"api.{code}.example",
         "services": {f"{code}{tok}": svc for tok, svc in PARTNER_SERVICES.items()}}
        for name, code, c in PARTNERS
    ]}


def write_estate(out: Path):
    header = "# Synthetic estate. All names and addresses are fictional. Generated by data/generate_estate.py.\n"
    estate = out / "data" / "estate"
    estate.mkdir(parents=True, exist_ok=True)
    for name, data in [("address-plan.yaml", address_plan()), ("routing.yaml", routing()),
                       ("partners.yaml", partners_file())]:
        (estate / name).write_text(header + yaml.safe_dump(data, sort_keys=False, width=120))

    for name, policy in build_estate().items():
        folder = out / "infra" / "envs" / name
        rcg = folder / "firewall_policy_rule_collection_groups"
        rcg.mkdir(parents=True, exist_ok=True)
        for spoke, group in policy["groups"].items():
            (rcg / f"{spoke}.tfvars").write_text(render_group(spoke, group))
        (folder / "ip-groups.tfvars").write_text(render_ip_groups(policy["env_site"]))


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=REPO, help="root to write data/estate and infra/envs under")
    write_estate(parser.parse_args().out)


if __name__ == "__main__":
    main()
