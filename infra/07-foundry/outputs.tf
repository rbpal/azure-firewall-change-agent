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

output "project_name" {
  description = "Name of the Foundry project. Later steps look it up by this name."
  value       = module.foundry_project.name
}

output "project_endpoints" {
  description = "Web addresses of the Foundry project."
  value       = module.foundry_project.endpoints
}

output "deployment_names" {
  description = "Model deployment names that code calls."
  value       = [for d in module.foundry_deployment : d.name]
}
