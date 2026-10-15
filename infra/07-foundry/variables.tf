# Variable names only. Values are set in one tfvars file per resource.

# ---- Shared, and the Foundry resource: values in foundry.tfvars

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

# ---- Foundry project: values in project.tfvars

variable "project_name" {
  description = "Name of the Foundry project."
  type        = string
}

variable "project_display_name" {
  description = "Name of the project shown in the Foundry portal."
  type        = string
}

variable "project_description" {
  description = "One line on what the project is for."
  type        = string
}

variable "project_identity_name" {
  description = "User-assigned identity the project signs in as, built by step 05-func."
  type        = string
}
