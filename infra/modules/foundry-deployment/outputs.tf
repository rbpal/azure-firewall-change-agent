output "id" {
  description = "Resource ID of the deployment."
  value       = azurerm_cognitive_deployment.this.id
}

output "name" {
  description = "Deployment name that code uses to call the model."
  value       = azurerm_cognitive_deployment.this.name
}
