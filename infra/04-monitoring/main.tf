# Step 04: where logs and traces land. The Function app (step 05) and the
# Foundry project (Step 03) both send to the same Application Insights.

module "log_analytics" {
  source = "../modules/log-analytics"

  name                         = var.log_name
  location                     = data.azurerm_resource_group.this.location
  resource_group_name          = data.azurerm_resource_group.this.name
  sku                          = var.log_sku
  retention_in_days            = var.log_retention_in_days
  daily_quota_gb               = var.log_daily_quota_gb
  local_authentication_enabled = var.log_local_authentication_enabled
  tags                         = var.tags
}

module "application_insights" {
  source = "../modules/application-insights"

  name                          = var.appi_name
  location                      = data.azurerm_resource_group.this.location
  resource_group_name           = data.azurerm_resource_group.this.name
  workspace_id                  = module.log_analytics.id
  application_type              = var.appi_application_type
  daily_data_cap_in_gb          = var.appi_daily_data_cap_in_gb
  local_authentication_disabled = var.appi_local_authentication_disabled
  tags                          = var.tags
}
