# Values for the resource group. Each name is declared in variables.tf.

location            = "eastus2"
resource_group_name = "rg-fwagentic-dev-01"

tags = {
  project    = "azure-firewall-change-agent"
  env        = "dev"
  managed_by = "terraform"
  step       = "02-rg"
}
