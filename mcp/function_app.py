"""The MCP server. Each tool is registered here and runs through gateway.run(),
which applies gate 2 before the tool sees anything."""

import azure.functions as func

from gateway import run
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
