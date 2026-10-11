# A private blob container in an existing storage account. Created through
# Azure Resource Manager, so no storage key or data role is needed to create it.
resource "azurerm_storage_container" "this" {
  name                  = var.name
  storage_account_id    = var.storage_account_id
  container_access_type = "private"
}
