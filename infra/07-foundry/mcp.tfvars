# Values for the project's connection to the MCP tool server (Step 04 Task 03).
# Each name is declared in variables.tf.
# Cost: a project connection has no charge; tool calls run on the existing
# Flex Consumption function app.

mcp_connection_name   = "mcp-fwagentic-tools"
mcp_function_app_name = "func-fwagentic-dev"
mcp_app_name          = "app-fwagentic-mcp-dev"
