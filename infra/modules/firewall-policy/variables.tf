variable "name" {
  description = "Name of the firewall policy, as routing.yaml names it."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the policy and its IP groups."
  type        = string
}

variable "location" {
  description = "Region of the policy and its IP groups: the env-site's region."
  type        = string
}

variable "sku" {
  description = "Policy tier. Basic, to match the firewall SKU."
  type        = string
}

variable "tags" {
  description = "Tags applied to the policy and each IP group."
  type        = map(string)
}

variable "ip_groups" {
  description = "IP groups by name, each with its CIDRs. Rules refer to them by name."
  type = map(object({
    name  = string
    cidrs = list(string)
  }))
}

variable "rule_collection_groups" {
  description = "One rule collection group per spoke file, plus hub. Rules are maps keyed NNN-name, so they keep their order."
  type        = any
}
