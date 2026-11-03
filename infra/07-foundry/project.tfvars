# Values for the Foundry project. Each name is declared in variables.tf.

project_name         = "proj-aif-fwagentic-dev"
project_display_name = "proj-aif-fwagentic-dev"
project_description  = "Firewall change agent: drafts rules from approved tickets. Dev."

# Built by step 05-func. It already holds Tools.Read on app-fwagentic-mcp-dev
# and is on func-fwagentic-dev's allow list, so the MCP tools accept it.
# A project has no fee of its own; cost comes from model use (Task 06).
project_identity_name = "uami-fwagentic-foundry-dev"

# Built by step 06-sync. sync-network signs in as it, and since it publishes the
# drafter's agent versions it holds Foundry User on this project only (ADR 0006).
# Foundry User is the narrowest built-in role that can write agent versions; it
# also allows model calls on this project. A role assignment has no cost.
sync_identity_name = "uami-fwagentic-sync-dev"
