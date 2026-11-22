# Values for the firewall policy. Each name is declared in variables.tf.
# Cost: $0. A firewall policy with zero or one firewall association is free
# (Microsoft Learn, Firewall Manager policy overview), and this demo attaches
# no firewall, so the Standard tier also costs $0. IP groups have no listed charge.
# Standard, not Basic: only Standard and Premium have DNS proxy, which network
# rules need to name an exact FQDN (Microsoft Learn, Azure Firewall features by SKU).

resource_group_name               = "rg-fwagentic-dev"
location                          = "eastus2"
firewall_policy_name              = "afwp-hub-dev-eastus2"
firewall_policy_sku               = "Standard"
firewall_policy_dns_proxy_enabled = true

tags = {
  project    = "azure-firewall-change-agent"
  env        = "dev"
  managed_by = "terraform"
  step       = "envs-dev-eastus2"
}
