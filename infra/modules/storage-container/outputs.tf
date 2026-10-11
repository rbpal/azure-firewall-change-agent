output "id" {
  description = "Resource Manager ID of the container. Role assignments scope to it."
  # Built from the account ID, so it is always the Resource Manager form a
  # role scope needs, never the blob URL.
  value = "${var.storage_account_id}/blobServices/default/containers/${azurerm_storage_container.this.name}"
}

output "name" {
  description = "Name of the container."
  value       = azurerm_storage_container.this.name
}
