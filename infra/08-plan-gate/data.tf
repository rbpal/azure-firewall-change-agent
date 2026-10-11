# Existing resources this step reads but does not create.

# The workload resource group, built by step 02-rg. The dev firewall policies
# live here, so the plan identity reads it.
data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

# The Terraform state account, built by the step 01 bootstrap with the Azure CLI.
data "azurerm_storage_account" "state" {
  name                = var.state_storage_account_name
  resource_group_name = var.state_resource_group_name
}
