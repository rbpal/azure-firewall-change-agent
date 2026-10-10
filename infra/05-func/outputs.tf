output "function_app_name" {
  description = "Name of the function app."
  value       = module.func.name
}

output "function_app_hostname" {
  description = "Host name of the function app."
  value       = module.func.default_hostname
}

output "function_app_principal_id" {
  description = "Object ID of the function app's managed identity. Later steps grant it read roles."
  value       = module.func.principal_id
}

output "storage_account_name" {
  description = "Name of the function app's storage account."
  value       = module.storage.name
}
