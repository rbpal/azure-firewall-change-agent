variable "scope" {
  description = "Resource ID the role applies to."
  type        = string
}

variable "role_definition_name" {
  description = "Built-in role name, such as Storage Blob Data Owner."
  type        = string
}

variable "principal_id" {
  description = "Object ID of the identity that gets the role."
  type        = string
}

variable "principal_type" {
  description = "Kind of identity: ServicePrincipal, User or Group. Managed identities are ServicePrincipal."
  type        = string
}
