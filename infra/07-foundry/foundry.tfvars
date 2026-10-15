# Values for the Foundry resource. Each name is declared in variables.tf.

resource_group_name = "rg-fwagentic-dev"

tags = {
  project    = "azure-firewall-change-agent"
  env        = "dev"
  managed_by = "terraform"
  step       = "07-foundry"
}

aif_name = "aif-fwagentic-dev"

# No free tier: Azure offers only S0 for AIServices (checked 2026-10-14 with
# az cognitiveservices account list-skus, eastus2). S0 has no fixed monthly fee;
# it bills per use, and use starts with the model deployments in a later task.
# There is no hard spending cap; budget-fwagentic-monthly alerts at 50/80/100%.
# Agreed with the user on 2026-10-14.
aif_sku_name = "S0"

# Checked free across Azure on 2026-10-14. Cannot change once set.
aif_custom_subdomain_name = "aif-fwagentic-dev"

# Entra sign-in only: API keys are refused.
aif_local_auth_enabled = false

# Demo keeps every service public with Entra-only sign-in. The enterprise
# design adds private endpoints (Step 07).
aif_public_network_access_enabled = true
