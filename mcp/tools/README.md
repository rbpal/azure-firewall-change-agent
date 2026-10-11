# mcp/tools

The tool logic: read-only tools that answer questions about the firewall network and Azure Resource Graph. The agent gets live state only from these tools.

Plain Python with no Azure Functions imports, so pytest can test each tool directly. `mcp/function_app.py` registers them with the MCP extension.

Every file here is a tool the agent can call. Code that loads repo data for the tools lives in `mcp/data_readers/`.

`dns_lookup_for_fqdn.py` asks Azure DNS (`168.63.129.16`) what a hostname resolves to. It only queries DNS; it never fetches the URL.
