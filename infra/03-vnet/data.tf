# Existing resources this step reads but does not create.

# The workload resource group, built by step 02-rg, found by name.
# The VNet is created in it and takes its region.
data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}
