variable "name" {
  description = "Name of the hosting plan."
  type        = string
}

variable "location" {
  description = "Azure region for the plan."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the plan."
  type        = string
}

variable "os_type" {
  description = "Operating system, Linux or Windows."
  type        = string
}

variable "sku_name" {
  description = "Plan SKU, such as FC1 for Flex Consumption."
  type        = string
}

variable "tags" {
  description = "Tags applied to the plan."
  type        = map(string)
}
