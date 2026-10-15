output "id" {
  description = "Resource ID of the Foundry project. Connections and deployments refer to it."
  value       = azurerm_cognitive_account_project.this.id
}

output "name" {
  description = "Name of the Foundry project."
  value       = azurerm_cognitive_account_project.this.name
}

output "endpoints" {
  description = "Web addresses of the project, such as the agents endpoint."
  value       = azurerm_cognitive_account_project.this.endpoints
}
