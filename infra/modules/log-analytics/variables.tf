variable "name" {
  description = "Name of the Log Analytics workspace."
  type        = string
}

variable "location" {
  description = "Azure region for the workspace."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the workspace."
  type        = string
}

variable "sku" {
  description = "Pricing tier. PerGB2018 is pay-as-you-go, which includes the monthly free allowance."
  type        = string
}

variable "retention_in_days" {
  description = "Days the workspace keeps data."
  type        = number
}

variable "daily_quota_gb" {
  description = "Most data the workspace takes in per day, in GB. Ingestion stops for the rest of the day when it is reached."
  type        = number
}

variable "local_authentication_enabled" {
  description = "Whether shared keys work. False means Entra sign-in only."
  type        = bool
}

variable "tags" {
  description = "Tags applied to the workspace."
  type        = map(string)
}
