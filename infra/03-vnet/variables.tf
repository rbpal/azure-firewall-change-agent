# Variable names only. Every value is set in vnet.tfvars.

# ---- Virtual network and its subnets: values in vnet.tfvars

variable "resource_group_name" {
  description = "Workload resource group, built by step 02-rg. The VNet takes its region."
  type        = string
}

variable "vnet_name" {
  description = "Name of the virtual network."
  type        = string
}

variable "address_space" {
  description = "Address ranges of the virtual network, in CIDR form."
  type        = list(string)
}

variable "tags" {
  description = "Tags applied to the virtual network."
  type        = map(string)
}

variable "subnets" {
  description = "Subnets to create inside the VNet, keyed by subnet name."
  type = map(object({
    address_prefixes = list(string)
    delegation = optional(object({
      name         = string
      service_name = string
      actions      = list(string)
    }))
  }))
}
