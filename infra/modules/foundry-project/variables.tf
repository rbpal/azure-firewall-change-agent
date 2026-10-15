variable "name" {
  description = "Name of the Foundry project."
  type        = string
}

variable "foundry_id" {
  description = "Resource ID of the Foundry resource that holds the project."
  type        = string
}

variable "location" {
  description = "Azure region. Must match the Foundry resource."
  type        = string
}

variable "display_name" {
  description = "Name shown in the Foundry portal."
  type        = string
}

variable "description" {
  description = "One line on what the project is for."
  type        = string
}

variable "identity_id" {
  description = "Resource ID of the user-assigned identity the project signs in as."
  type        = string
}

variable "tags" {
  description = "Tags applied to the project."
  type        = map(string)
}
