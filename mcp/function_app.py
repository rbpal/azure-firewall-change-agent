"""The MCP server. Each tool is registered here and runs through gateway.run(),
which applies gate 2 before the tool sees anything."""

import json

import azure.functions as func

from gateway import run
from tools.dns_lookup_for_fqdn import dns_lookup_for_fqdn
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
