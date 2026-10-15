# Variable names only. Values are set in foundry.tfvars.

variable "resource_group_name" {
  description = "Workload resource group, built by step 02-rg. The Foundry resource takes its region."
  type        = string
}

variable "tags" {
  description = "Tags applied to the Foundry resource."
  type        = map(string)
}

variable "aif_name" {
  description = "Name of the Foundry resource."
  type        = string
}

variable "aif_sku_name" {
  description = "Pricing tier of the Foundry resource."
  type        = string
}

variable "aif_custom_subdomain_name" {
  description = "Prefix of the Foundry resource's web address. Cannot change later."
  type        = string
}

variable "aif_local_auth_enabled" {
  description = "Whether API keys work on the Foundry resource."
  type        = bool
}

variable "aif_public_network_access_enabled" {
  description = "Whether the Foundry resource is reachable over the public internet."
  type        = bool
}
