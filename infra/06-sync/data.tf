# Existing resources this step reads but does not create.

# The workload resource group, built by step 02-rg.
data "azurerm_resource_group" "this" {
  name = var.resource_group_name
}

# The function app's storage account, built by step 05-func. The snapshot
# container goes in it. The function app's identity already holds Storage Blob
# Data Owner on this account, so it can read the container with no new role.
data "azurerm_storage_account" "func" {
  name                = var.storage_account_name
  resource_group_name = var.resource_group_name
}
