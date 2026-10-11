# mcp/data_readers

Loads the repo data the tools answer from. The agent never calls these; only the tools in `mcp/tools/` do.

`read_addressplan_routing.py` loads the network data files (address plan, routing) and checks them as it reads.

`read_env_site_ipgroup.py` reads the rules files and IP groups that `duplicate_rule_check` compares against.

Plain Python with no Azure Functions imports, so pytest can test each reader directly.
