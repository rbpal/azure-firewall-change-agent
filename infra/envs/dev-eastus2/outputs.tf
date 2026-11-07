output "firewall_policy_id" {
  description = "Resource ID of this env-site's firewall policy."
  value       = module.firewall_policy.id
}

output "ip_group_ids" {
  description = "Resource ID of each IP group, by its key in ip-groups.tfvars."
  value       = module.firewall_policy.ip_group_ids
}
