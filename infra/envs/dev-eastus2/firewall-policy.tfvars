# Values for the firewall policy. Each name is declared in variables.tf.
# Cost: $0. A firewall policy with zero or one firewall association is free
# (Microsoft Learn, Firewall Manager policy overview), and this demo attaches
# no firewall. IP groups have no listed charge.

resource_group_name  = "rg-fwagentic-dev"
location             = "eastus2"
firewall_policy_name = "afwp-hub-dev-eastus2"
firewall_policy_sku  = "Basic"

tags = {
  project    = "azure-firewall-change-agent"
  env        = "dev"
  managed_by = "terraform"
  step       = "envs-dev-eastus2"
}
