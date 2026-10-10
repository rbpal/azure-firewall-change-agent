output "id" {
  description = "Resource ID of the workspace."
  value       = azurerm_log_analytics_workspace.this.id
}

output "name" {
  description = "Name of the workspace."
  value       = azurerm_log_analytics_workspace.this.name
}
