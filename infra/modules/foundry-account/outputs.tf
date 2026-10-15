output "id" {
  description = "Resource ID of the Foundry resource. Projects are created under it."
  value       = azurerm_cognitive_account.this.id
}

output "name" {
  description = "Name of the Foundry resource. Later steps look it up by this name."
  value       = azurerm_cognitive_account.this.name
}

output "endpoint" {
  description = "Web address callers use."
  value       = azurerm_cognitive_account.this.endpoint
}

output "principal_id" {
  description = "Object ID of the resource's own managed identity, for role assignments in later steps."
  value       = azurerm_cognitive_account.this.identity[0].principal_id
}
