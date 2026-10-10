# Step 05: the function app that hosts the agent's tools, its storage and its
# hosting plan, plus the two roles it needs because storage and Application
# Insights both refuse keys.

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
