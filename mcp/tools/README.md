# mcp/tools

The tool logic: read-only tools that answer questions about the firewall network and Azure Resource Graph. The agent gets live state only from these tools.

Plain Python with no Azure Functions imports, so pytest can test each tool directly. `mcp/function_app.py` registers them with the MCP extension.

`network.py` is not a tool. It loads the network data files (address plan, routing) that the tools answer from, and checks them as it reads.
