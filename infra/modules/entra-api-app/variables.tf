variable "display_name" {
  description = "Display name of the app registration."
  type        = string
}

variable "owners" {
  description = "Object IDs of the owners of the app registration and its service principal."
  type        = list(string)
}

variable "app_role_value" {
  description = "Value of the app role callers must hold, such as Tools.Read. It appears in the token's roles claim."
  type        = string
}

variable "app_role_description" {
  description = "What the app role allows."
  type        = string
}

variable "pre_authorized_client_ids" {
  description = "Client IDs allowed to request the delegated scope without consent, such as Azure CLI for tests."
  type        = list(string)
}
