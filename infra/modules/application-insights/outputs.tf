output "id" {
  description = "Resource ID of Application Insights."
  value       = azurerm_application_insights.this.id
}

output "name" {
  description = "Name of Application Insights."
  value       = azurerm_application_insights.this.name
}

output "connection_string" {
  description = "Connection string senders use. With local auth disabled it identifies the resource but does not grant access."
  value       = azurerm_application_insights.this.connection_string
  sensitive   = true
}
