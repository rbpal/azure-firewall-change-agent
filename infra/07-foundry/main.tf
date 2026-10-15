# Step 07: the Foundry resource (Step 03 Task 04) and its project (Task 05).
# The model deployments (Task 06) are added in a later task.

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

module "foundry_project" {
  source = "../modules/foundry-project"

  name         = var.project_name
  foundry_id   = module.foundry_account.id
  location     = data.azurerm_resource_group.this.location
  display_name = var.project_display_name
  description  = var.project_description
  identity_id  = data.azurerm_user_assigned_identity.project.id
  tags         = var.tags
}
