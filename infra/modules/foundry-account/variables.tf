variable "name" {
  description = "Name of the Foundry resource."
  type        = string
}

variable "location" {
  description = "Azure region for the Foundry resource."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the Foundry resource."
  type        = string
}

variable "sku_name" {
  description = "Pricing tier. AIServices offers S0 only: no fixed fee, billed per use."
  type        = string
}

variable "custom_subdomain_name" {
  description = "Prefix of the resource's web address, needed for Entra sign-in. Unique across Azure; cannot change later."
  type        = string
}

variable "local_auth_enabled" {
  description = "Whether API keys work. False means callers must sign in with Entra."
  type        = bool
}

variable "public_network_access_enabled" {
  description = "Whether the resource is reachable over the public internet."
  type        = bool
}

variable "tags" {
  description = "Tags applied to the Foundry resource."
  type        = map(string)
}
