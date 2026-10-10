output "vnet_id" {
  description = "Resource ID of the virtual network."
  value       = module.vnet.id
}

output "vnet_name" {
  description = "Name of the virtual network. Later steps look it up by this name."
  value       = module.vnet.name
}

output "subnet_ids" {
  description = "Resource IDs of the subnets, keyed by subnet name."
  value       = module.vnet.subnet_ids
}
