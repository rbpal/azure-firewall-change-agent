variable "name" {
  description = "Name of the virtual network."
  type        = string
}

variable "location" {
  description = "Azure region for the virtual network."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the virtual network."
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
  description = "Subnets to create, keyed by subnet name. A subnet may be delegated to one Azure service."
  type = map(object({
    address_prefixes = list(string)
    delegation = optional(object({
      name         = string
      service_name = string
      actions      = list(string)
    }))
  }))
}
