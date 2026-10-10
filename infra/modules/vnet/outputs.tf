output "id" {
  description = "Resource ID of the virtual network."
  value       = azurerm_virtual_network.this.id
}

output "name" {
  description = "Name of the virtual network."
  value       = azurerm_virtual_network.this.name
}

output "subnet_ids" {
  description = "Resource IDs of the subnets, keyed by subnet name."
  value       = { for k, s in azurerm_subnet.this : k => s.id }
}
