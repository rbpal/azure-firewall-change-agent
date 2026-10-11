# Variable names only. Values are set in tfvars files.

# ---- The policy: values in firewall-policy.tfvars

variable "resource_group_name" {
  description = "Workload resource group, built by step 02-rg."
  type        = string
}

variable "location" {
  description = "Region of this env-site. The policy and IP groups go here, which may differ from the resource group's region."
  type        = string
}

variable "firewall_policy_name" {
  description = "Name of this env-site's firewall policy, as routing.yaml names it."
  type        = string
}

variable "firewall_policy_sku" {
  description = "Policy tier: Basic, to match the firewall SKU."
  type        = string
}

variable "tags" {
  description = "Tags applied to the policy and its IP groups."
  type        = map(string)
}

# ---- IP groups: values in ip-groups.tfvars

variable "ip_groups" {
  description = "IP groups by name, each with its CIDRs."
  type = map(object({
    name  = string
    cidrs = list(string)
  }))
}

# ---- Rule collection groups: one variable per file in firewall_policy_rule_collection_groups/.
# Each file sets only its own variable, so two files can never overwrite each other.

variable "hub" {
  description = "Shared hub rules. Values in firewall_policy_rule_collection_groups/hub.tfvars."
  type        = any
}

variable "ledg" {
  description = "Rules for the ledg spoke. Values in firewall_policy_rule_collection_groups/ledg.tfvars."
  type        = any
}

variable "rprt" {
  description = "Rules for the rprt spoke. Values in firewall_policy_rule_collection_groups/rprt.tfvars."
  type        = any
}

variable "sett" {
  description = "Rules for the sett spoke. Values in firewall_policy_rule_collection_groups/sett.tfvars."
  type        = any
}

variable "xfer" {
  description = "Rules for the xfer spoke. Values in firewall_policy_rule_collection_groups/xfer.tfvars."
  type        = any
}
