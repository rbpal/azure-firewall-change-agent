# Existing resources this root reads but does not create.

# The workload resource group, built by step 02-rg.
data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}
