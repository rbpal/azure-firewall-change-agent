output "id" {
  description = "Resource ID of the function app."
  value       = azurerm_function_app_flex_consumption.this.id
}

output "name" {
  description = "Name of the function app."
  value       = azurerm_function_app_flex_consumption.this.name
}

output "default_hostname" {
  description = "Host name of the function app."
  value       = azurerm_function_app_flex_consumption.this.default_hostname
}

output "principal_id" {
  description = "Object ID of the app's system-assigned managed identity."
  value       = azurerm_function_app_flex_consumption.this.identity[0].principal_id
}
