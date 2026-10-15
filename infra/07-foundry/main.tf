# Step 07: the Foundry resource (Step 03 Task 04), its project (Task 05), and
# the model deployments plus Foundry User for the laptop (Task 06).

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

module "foundry_deployment" {
  source   = "../modules/foundry-deployment"
  for_each = var.deployments

  name          = each.key
  foundry_id    = module.foundry_account.id
  model_name    = each.value.model_name
  model_version = each.value.model_version
  sku_name      = each.value.sku_name
  capacity      = each.value.capacity
}

module "terraform_user_foundry_user" {
  source = "../modules/role-assignment"
  count  = var.foundry_user_role_for_terraform_user ? 1 : 0

  scope                = module.foundry_account.id
  role_definition_name = "Foundry User"
  principal_id         = data.azurerm_client_config.current.object_id
  principal_type       = "User"
}
