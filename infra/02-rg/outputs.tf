output "resource_group_name" {
  description = "Name of the workload resource group. Later steps look it up by this name."
  value       = module.resource_group.name
}

output "resource_group_id" {
  description = "Resource ID of the workload resource group."
  value       = module.resource_group.id
}

output "budget_id" {
  description = "Resource ID of the subscription budget."
  value       = module.budget.id
}
