output "foundry_id" {
  description = "Resource ID of the Foundry resource."
  value       = module.foundry_account.id
}

output "foundry_name" {
  description = "Name of the Foundry resource. Later steps look it up by this name."
  value       = module.foundry_account.name
}

output "foundry_endpoint" {
  description = "Web address of the Foundry resource."
  value       = module.foundry_account.endpoint
}
