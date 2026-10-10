# Values for the tool server's app registration. Each name is declared in variables.tf.
# Cost: Entra app registrations and app role assignments are free.

mcp_app_name             = "app-fwagentic-mcp-dev"
mcp_app_role_value       = "Tools.Read"
mcp_app_role_description = "Call the read-only MCP tools on func-fwagentic-dev."

# Demo only: Azure CLI, so you can get a token with az account
# get-access-token and test the tools from a laptop. Names come from
# Microsoft's published app list; data.tf looks up their client IDs.
# Set to [] to leave only the Foundry identity.
mcp_test_clients = ["MicrosoftAzureCli"]

# Demo only: you get Tools.Read for those tests. Set false to remove it.
mcp_role_for_terraform_user = true
