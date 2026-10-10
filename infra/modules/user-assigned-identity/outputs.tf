output "id" {
  description = "Resource ID of the identity."
  value       = azurerm_user_assigned_identity.this.id
}

output "client_id" {
  description = "Client ID of the identity. Allow lists match on it."
  value       = azurerm_user_assigned_identity.this.client_id
}

output "principal_id" {
  description = "Object ID of the identity's service principal. Role assignments point at it."
  value       = azurerm_user_assigned_identity.this.principal_id
}
