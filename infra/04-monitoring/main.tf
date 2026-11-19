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

# Observability stage 1: one workbook that reads the workspace above. It adds
# no data and changes neither resource. Every query is a file in
# workbook/kql/; a line "// @include agent_runs" is replaced by the shared
# agent-runs block (_agent_runs.kql), so that logic is written once.
locals {
  workbook_kql_dir    = "${path.module}/workbook/kql"
  workbook_agent_runs = file("${local.workbook_kql_dir}/_agent_runs.kql")
  workbook_queries = {
    for f in fileset(local.workbook_kql_dir, "*.kql") :
    trimsuffix(f, ".kql") => replace(file("${local.workbook_kql_dir}/${f}"), "// @include agent_runs", local.workbook_agent_runs)
    if !startswith(f, "_")
  }
}

module "workbook" {
  source = "../modules/application-insights-workbook"

  # Azure needs a GUID name. uuidv5 makes the same one from the same text on
  # every plan, so no GUID is written in this repo.
  name                = uuidv5("url", var.workbook_name_seed)
  resource_group_name = data.azurerm_resource_group.this.name
  location            = data.azurerm_resource_group.this.location
  display_name        = var.workbook_display_name
  description         = var.workbook_description
  source_id           = lower(module.log_analytics.id)
  tags                = var.tags

  # jsondecode fails the plan if the template does not render valid JSON.
  data_json = jsonencode(jsondecode(templatefile("${path.module}/workbook/fwagent-observability.workbook.json.tftpl", {
    queries      = local.workbook_queries
    workspace_id = module.log_analytics.id
    daily_cap_mb = tostring(var.log_daily_quota_gb * 1000)
  })))
}
