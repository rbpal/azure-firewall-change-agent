# Step 05: the function app that hosts the agent's tools, its storage and its
# hosting plan, plus the two roles it needs because storage and Application
# Insights both refuse keys.
#
# Part 2: the app's front door in Entra ID. An app registration that callers
# request tokens for, the identity Foundry signs in as, the role it holds, and
# the built-in auth that checks every call.

module "storage" {
  source = "../modules/storage-account"

  name                      = var.storage_name
  location                  = data.azurerm_resource_group.this.location
  resource_group_name       = data.azurerm_resource_group.this.name
  account_tier              = var.storage_account_tier
  replication_type          = var.storage_replication_type
  shared_access_key_enabled = var.storage_shared_access_key_enabled
  containers                = [var.storage_package_container]
  tags                      = var.tags
}

module "plan" {
  source = "../modules/service-plan"

  name                = var.plan_name
  location            = data.azurerm_resource_group.this.location
  resource_group_name = data.azurerm_resource_group.this.name
  os_type             = var.plan_os_type
  sku_name            = var.plan_sku_name
  tags                = var.tags
}

module "func" {
  source = "../modules/function-app-flex"

  name                                   = var.func_name
  location                               = data.azurerm_resource_group.this.location
  resource_group_name                    = data.azurerm_resource_group.this.name
  service_plan_id                        = module.plan.id
  runtime_name                           = var.func_runtime_name
  runtime_version                        = var.func_runtime_version
  instance_memory_in_mb                  = var.func_instance_memory_in_mb
  maximum_instance_count                 = var.func_maximum_instance_count
  storage_container_endpoint             = "${module.storage.primary_blob_endpoint}${var.storage_package_container}"
  storage_account_name                   = module.storage.name
  subnet_id                              = data.azurerm_subnet.func.id
  application_insights_connection_string = data.azurerm_application_insights.this.connection_string
  tags                                   = var.tags

  auth = {
    client_id            = module.mcp_api.client_id
    tenant_auth_endpoint = "https://login.microsoftonline.com/${data.azuread_client_config.current.tenant_id}/v2.0"
    allowed_audiences    = [module.mcp_api.identifier_uri]
    allowed_applications = concat([module.caller_identity.client_id], local.mcp_test_client_ids)
  }
}

# The Functions host reads and writes its storage with the app's identity.
module "role_storage" {
  source = "../modules/role-assignment"

  scope                = module.storage.id
  role_definition_name = "Storage Blob Data Owner"
  principal_id         = module.func.principal_id
  principal_type       = "ServicePrincipal"
}

# Application Insights refuses the key, so the app needs this role to send.
module "role_appi" {
  source = "../modules/role-assignment"

  scope                = data.azurerm_application_insights.this.id
  role_definition_name = "Monitoring Metrics Publisher"
  principal_id         = module.func.principal_id
  principal_type       = "ServicePrincipal"
}

# ---- Part 2: Entra sign-in for the MCP tools

module "mcp_api" {
  source = "../modules/entra-api-app"

  display_name              = var.mcp_app_name
  owners                    = [data.azuread_client_config.current.object_id]
  app_role_value            = var.mcp_app_role_value
  app_role_description      = var.mcp_app_role_description
  pre_authorized_client_ids = local.mcp_test_client_ids
}

# The identity Foundry Agent Service signs in as. Attached to the project in
# Step 03; created here so its role exists first.
module "caller_identity" {
  source = "../modules/user-assigned-identity"

  name                = var.uami_name
  location            = data.azurerm_resource_group.this.location
  resource_group_name = data.azurerm_resource_group.this.name
  tags                = var.tags
}

module "caller_tools_read" {
  source = "../modules/app-role-assignment"

  app_role_id         = module.mcp_api.app_role_id
  principal_object_id = module.caller_identity.principal_id
  resource_object_id  = module.mcp_api.service_principal_object_id
}

# Demo only: lets the person running Terraform test the tools from a laptop.
module "tester_tools_read" {
  source = "../modules/app-role-assignment"
  count  = var.mcp_role_for_terraform_user ? 1 : 0

  app_role_id         = module.mcp_api.app_role_id
  principal_object_id = data.azuread_client_config.current.object_id
  resource_object_id  = module.mcp_api.service_principal_object_id
}
