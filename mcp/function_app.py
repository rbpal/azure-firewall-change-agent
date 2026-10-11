"""The MCP server. Each tool is registered here and runs through gateway.run(),
which applies gate 2 before the tool sees anything."""

import json

import azure.functions as func

from data_readers.blob_source import snapshot_source
from gateway import run
from tools.dns_lookup_for_fqdn import dns_lookup_for_fqdn
from tools.duplicate_rule_check import duplicate_rule_check
from tools.locate_address_for_env_site import locate_address_for_env_site
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
                 "belongs to, and that env-site's hub firewall and firewall policy. Reads the address plan "
                 "and routing from the latest copy of main and names the commit it read."),
    tool_properties=json.dumps([{
        "propertyName": "address",
        "propertyType": "string",
        "description": "An IPv4 address such as 10.100.20.14, or a CIDR such as 10.100.20.0/24.",
    }]),
)
def locate_address_for_env_site_tool(context: str) -> str:
    return run(context, locate_address_for_env_site, source=snapshot_source())


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
         "description": ("The new rule's fields, such as protocols, source_addresses or source_ip_groups, "
                         "destination_addresses, destination_fqdns and destination_ports.")},
    ]),
)
def duplicate_rule_check_tool(context: str) -> str:
    return run(context, duplicate_rule_check, source=snapshot_source())
