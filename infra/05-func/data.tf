# Existing resources this step reads but does not create.

# The workload resource group, built by step 02-rg.
data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

# The delegated subnet the function app joins, built by step 03-vnet.
data "azurerm_subnet" "func" {
  name                 = var.subnet_name
  virtual_network_name = var.vnet_name
  resource_group_name  = var.resource_group_name
}

# Where the function app sends its logs, built by step 04-monitoring.
data "azurerm_application_insights" "this" {
  name                = var.appi_name
  resource_group_name = var.resource_group_name
}

# Who is running Terraform: gives the tenant ID for the token issuer and the
# object ID that owns the app registration. Nothing is written to a file.
data "azuread_client_config" "current" {}

# Client IDs of Microsoft's own apps, such as Azure CLI, looked up by name so
# no GUID sits in a committed file.
data "azuread_application_published_app_ids" "well_known" {}

locals {
  mcp_test_client_ids = [for name in var.mcp_test_clients : data.azuread_application_published_app_ids.well_known.result[name]]
}
