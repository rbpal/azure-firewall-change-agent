# mcp/tools

The tool logic: read-only tools that answer questions about the firewall estate and Azure Resource Graph. The agent gets live state only from these tools.

Plain Python with no Azure Functions imports, so pytest can test each tool directly. `mcp/function_app.py` registers them with the MCP extension.
