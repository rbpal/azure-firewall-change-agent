output "id" {
  description = "Resource ID of the firewall policy."
  value       = azurerm_firewall_policy.this.id
}

output "name" {
  description = "Name of the firewall policy."
  value       = azurerm_firewall_policy.this.name
}

output "ip_group_ids" {
  description = "Resource ID of each IP group, by name."
  value       = local.ip_group_ids
}
