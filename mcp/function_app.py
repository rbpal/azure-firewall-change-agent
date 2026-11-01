"""The MCP server. Each tool is registered here and runs through gateway.run(),
which applies gate 2 before the tool sees anything."""

import json

import azure.functions as func

from gateway import run
from tools.dnat_port_check import dnat_port_check
from tools.dns_lookup_for_fqdn import dns_lookup_for_fqdn
from tools.duplicate_rule_check import duplicate_rule_check
from tools.locate_address_for_env_site import locate_address_for_env_site
from tools.resolve_env_site import resolve_env_site
from tools.whoami import whoami

app = func.FunctionApp()


@app.mcp_tool_trigger(
    arg_name="context",
    tool_name="whoami",
    description="Report the caller's identity and roles as the tool server sees them. Diagnostic only.",
    tool_properties="[]",
)
def whoami_tool(context: str) -> str:
    return run(context, whoami)


@app.mcp_tool_trigger(
    arg_name="context",
    tool_name="dns_lookup_for_fqdn",
    description=("Check that a URL or hostname is valid and whether it resolves to an IP address, "
                 "using Azure DNS from inside the VNet. Returns resolves true or false with a reason, "
                 "the CNAME chain, A and AAAA records and TTL. Lookup only; it never opens the URL."),
    tool_properties=json.dumps([{
        "propertyName": "target",
        "propertyType": "string",
        "description": "A URL such as https://www.example.com/path, or a bare hostname.",
    }]),
)
def dns_lookup_for_fqdn_tool(context: str) -> str:
    return run(context, dns_lookup_for_fqdn)


@app.mcp_tool_trigger(
    arg_name="context",
    tool_name="locate_address_for_env_site",
    description=("Find which environment, site, spoke, VNet and IP group an internal IPv4 address or CIDR "
                 "belongs to, and that env-site's hub firewall and firewall policy. Given an IP group name, list "
                 "every plan range that names it, with origin azure, onprem or mixed; null when no range does. "
                 "An address no plan range contains also answers address_space: rfc1918, non_rfc1918 or mixed. "
                 "Reads the address plan and routing from the copy of main (the pinned snapshot, else the latest) "
                 "and names the commit it read."),
    tool_properties=json.dumps([{
        "propertyName": "address",
        "propertyType": "string",
        "description": ("An IPv4 address such as 10.100.20.14, a CIDR such as 10.100.20.0/24, "
                        "or an IP group name such as ipg-onprem-primary."),
    }]),
)
def locate_address_for_env_site_tool(context: str) -> str:
    return run(context, locate_address_for_env_site, snapshot=True)


@app.mcp_tool_trigger(
    arg_name="context",
    tool_name="resolve_env_site",
    description=("Give the env-site name, such as prod-centralus, for an environment and an Azure site "
                 "(primary or dr), with that env-site's region, hub firewall, policy and public IP. Use it "
                 "when the ticket gives no internal address for a selected site. Reads routing from the copy "
                 "of main (the pinned snapshot, else the latest) and names the commit it read. Answers "
                 "resolved false, with the pairs routing lists, when there is not exactly one match."),
    tool_properties=json.dumps([
        {"propertyName": "environment", "propertyType": "string",
         "description": "The ticket's environment, such as prod."},
        {"propertyName": "site", "propertyType": "string",
         "description": "The ticket's Azure site: primary or dr."},
    ]),
)
def resolve_env_site_tool(context: str) -> str:
    return run(context, resolve_env_site, snapshot=True)


@app.mcp_tool_trigger(
    arg_name="context",
    tool_name="duplicate_rule_check",
    description=("Check whether an existing firewall rule in one env-site already allows all of a new rule's "
                 "traffic. Lists each match as duplicate or covers, with its key, file and commit. "
                 "An empty list means the new rule is needed."),
    tool_properties=json.dumps([
        {"propertyName": "env_site", "propertyType": "string",
         "description": "The env-site to check, such as dev-eastus2."},
        {"propertyName": "type", "propertyType": "string",
         "description": "The new rule's type: network, application or dnat."},
        {"propertyName": "rule", "propertyType": "object",
         "description": ("The new rule's fields, each a list of strings except the dnat fields destination_address, "
                         "translated_address and translated_port, which are single strings. network: protocols such as "
                         "[\"TCP\"], source_addresses or source_ip_groups, destination_addresses, destination_ip_groups "
                         "or destination_fqdns, and destination_ports such as [\"443\"]. application: protocols with the "
                         "port inside, such as [\"Https:443\"], source_addresses or source_ip_groups, and "
                         "destination_fqdns such as [\"api.example.com\"] (a hostname, never a URL); no "
                         "destination_ports. dnat: protocols, source_addresses or source_ip_groups, "
                         "destination_address, destination_ports, translated_address and translated_port.")},
    ]),
)
def duplicate_rule_check_tool(context: str) -> str:
    return run(context, duplicate_rule_check, snapshot=True)


@app.mcp_tool_trigger(
    arg_name="context",
    tool_name="dnat_port_check",
    description=("Check whether a TCP port is already published on one env-site's firewall public IP by any DNAT "
                 "rule in its policy, hub included. Answers conflicts_found with each rule that holds the port, "
                 "no_conflicts, or inconclusive when a rules file or rule cannot be read. Names the commit it read."),
    tool_properties=json.dumps([
        {"propertyName": "env_site", "propertyType": "string",
         "description": "The env-site to check, such as stage-eastus2."},
        {"propertyName": "protocols", "propertyType": "string", "isArray": True,
         "description": "The ticket's protocol: [\"TCP\"]. New inbound DNAT is TCP only (workflow policy)."},
        {"propertyName": "destination_ports", "propertyType": "string", "isArray": True,
         "description": "The ticket's ports, such as [\"22\"] or [\"2220-2224\"]; a DNAT port is 1-63999."},
    ]),
)
def dnat_port_check_tool(context: str) -> str:
    return run(context, dnat_port_check, snapshot=True)
