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
