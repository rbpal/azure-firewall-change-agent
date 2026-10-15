# Existing resources this step reads but does not create.

# The workload resource group, built by step 02-rg, found by name.
# The Foundry resource is created in it and takes its region.
data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

# The project's identity, built by step 05-func, found by name. It holds the
# Tools.Read role that the MCP tool server checks.
data "azurerm_user_assigned_identity" "project" {
  name                = var.project_identity_name
  resource_group_name = data.azurerm_resource_group.this.name
}

# Who is running Terraform. Used to give that person the Foundry User role on
# this resource only.
data "azurerm_client_config" "current" {}

# Application Insights, built by step 04-monitoring, found by name. The project
# sends agent traces here.
data "azurerm_application_insights" "this" {
  name                = var.appi_name
  resource_group_name = data.azurerm_resource_group.this.name
}

# The Log Analytics workspace, built by step 04-monitoring, found by name.
# Platform logs from the Foundry resource and project go here.
data "azurerm_log_analytics_workspace" "this" {
  name                = var.law_name
  resource_group_name = data.azurerm_resource_group.this.name
}
