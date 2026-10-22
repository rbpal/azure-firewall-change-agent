# Step 07: the Foundry resource (Step 03 Task 04), its project (Task 05), the
# model deployments plus Foundry User for the laptop (Task 06), and the project's
# connection to Application Insights for traces (Task 07), and the project's
# connection to the MCP tool server (Step 04 Task 03).

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

module "appi_connection" {
  source = "../modules/foundry-project-connection"

  name        = var.appi_connection_name
  project_id  = module.foundry_project.id
  category    = "AppInsights"
  auth_type   = "ProjectManagedIdentity"
  target      = data.azurerm_application_insights.this.id
  api_version = var.connection_api_version

  # Azure requires it for AppInsights. With local auth off on appi-fwagentic-dev
  # it only identifies the resource; it grants no access on its own.
  extra_metadata = {
    ApplicationInsightsConnectionString = data.azurerm_application_insights.this.connection_string
  }
}

# The project's identity sends traces with Entra sign-in, so it needs this role.
# Application Insights refuses the ingestion key (section 04).
module "project_identity_metrics_publisher" {
  source = "../modules/role-assignment"

  scope                = data.azurerm_application_insights.this.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = data.azurerm_user_assigned_identity.project.principal_id
  principal_type       = "ServicePrincipal"
}

# Platform logs: Azure's own records about the Foundry resource and project,
# sent to the workspace. Separate from the traces above. Categories are set in
# diagnostics.tfvars.
module "foundry_account_diagnostics" {
  source = "../modules/diagnostic-setting"

  name                       = var.diagnostic_setting_name
  target_resource_id         = module.foundry_account.id
  log_analytics_workspace_id = data.azurerm_log_analytics_workspace.this.id
  log_categories             = var.foundry_account_log_categories
}

module "foundry_project_diagnostics" {
  source = "../modules/diagnostic-setting"

  name                       = var.diagnostic_setting_name
  target_resource_id         = module.foundry_project.id
  log_analytics_workspace_id = data.azurerm_log_analytics_workspace.this.id
  log_categories             = var.foundry_project_log_categories
}

# The agent's tools: Foundry Agent Service calls the MCP server on the function
# app as the project's identity, which holds Tools.Read and is on the app's
# allow list (step 05-func). No key is stored: the token is requested per call
# for the tool app's audience.
module "mcp_connection" {
  source = "../modules/foundry-project-connection"

  name               = var.mcp_connection_name
  project_id         = module.foundry_project.id
  category           = "RemoteTool"
  auth_type          = "ProjectManagedIdentity"
  target             = local.mcp_endpoint
  target_is_resource = false
  audience           = one(data.azuread_application.mcp.identifier_uris)
  api_version        = var.connection_api_version
}

locals {
  mcp_endpoint = "https://${var.mcp_function_app_name}.azurewebsites.net/runtime/webhooks/mcp"
}
