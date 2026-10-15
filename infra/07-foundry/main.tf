# Step 07: the Foundry resource (Step 03 Task 04). The project (Task 05) and
# the model deployments (Task 06) are added under it in later tasks.

module "foundry_account" {
  source = "../modules/foundry-account"

  name                          = var.aif_name
  location                      = data.azurerm_resource_group.this.location
  resource_group_name           = data.azurerm_resource_group.this.name
  sku_name                      = var.aif_sku_name
  custom_subdomain_name         = var.aif_custom_subdomain_name
  local_auth_enabled            = var.aif_local_auth_enabled
  public_network_access_enabled = var.aif_public_network_access_enabled
  tags                          = var.tags
}
