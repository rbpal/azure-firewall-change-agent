variable "name" {
  description = "Name of the storage account. 3 to 24 lower-case letters and digits, unique across Azure."
  type        = string
}

variable "location" {
  description = "Azure region for the storage account."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the storage account."
  type        = string
}

variable "account_tier" {
  description = "Performance tier, Standard or Premium."
  type        = string
}

variable "replication_type" {
  description = "Replication, such as LRS (three copies in one datacentre, the cheapest)."
  type        = string
}

variable "shared_access_key_enabled" {
  description = "Whether storage keys work. False means Entra sign-in only."
  type        = bool
}

variable "containers" {
  description = "Names of the blob containers to create. They are private."
  type        = list(string)
}

variable "tags" {
  description = "Tags applied to the storage account."
  type        = map(string)
}
