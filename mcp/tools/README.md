# mcp/tools

The tool logic: read-only tools that answer questions about the firewall network and Azure Resource Graph. The agent gets live state only from these tools.

Plain Python with no Azure Functions imports, so pytest can test each tool directly. `mcp/function_app.py` registers them with the MCP extension.

`read_addressplan_routing.py` is not a tool. It loads the network data files (address plan, routing) that the tools answer from, and checks them as it reads.

`read_env_site_ipgroup.py` is not a tool either. It reads the rules files and IP groups that `duplicate_rule_check` compares against.

`dns_lookup_for_fqdn.py` asks Azure DNS (`168.63.129.16`) what a hostname resolves to. It only queries DNS; it never fetches the URL.
