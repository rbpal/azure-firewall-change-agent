# Values for the Foundry project. Each name is declared in variables.tf.

project_name         = "proj-aif-fwagentic-dev"
project_display_name = "proj-aif-fwagentic-dev"
project_description  = "Firewall change agent: drafts rules from approved tickets. Dev."

# Built by step 05-func. It already holds Tools.Read on app-fwagentic-mcp-dev
# and is on func-fwagentic-dev's allow list, so the MCP tools accept it.
# A project has no fee of its own; cost comes from model use (Task 06).
project_identity_name = "uami-fwagentic-foundry-dev"
