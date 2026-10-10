# Existing resources this step reads but does not create.

# The workload resource group, built by step 02-rg, found by name.
# The workspace and Application Insights are created in it and take its region.
data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}
