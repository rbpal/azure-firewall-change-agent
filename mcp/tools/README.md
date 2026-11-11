# mcp/tools

The tools on the MCP server. `mcp/function_app.py` registers each one.

| Tool | What it answers |
| --- | --- |
| `dns_lookup_for_fqdn.py` | Is a URL valid, and what does its hostname resolve to in Azure DNS (`168.63.129.16`)? It only asks DNS; it never fetches the URL. |
| `locate_address_for_env_site.py` | Which environment, site and IP group an internal address belongs to, and that env-site's hub firewall, policy and public IP. |
| `resolve_env_site.py` | Which env-site matches a ticket's environment and Azure site, when the ticket gives no internal address. |
| `duplicate_rule_check.py` | Does an existing rule in the env-site already allow all of a new rule's traffic? |
| `dnat_port_check.py` | Is a TCP port already published on the env-site's firewall public IP? |
| `code_version.py` | A SHA-256 hash of the server's own code, so the workflow can refuse a server that does not run main's code. The agent is not given this tool. |
