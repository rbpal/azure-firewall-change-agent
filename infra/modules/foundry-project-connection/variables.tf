variable "name" {
  description = "Connection name: letters, digits, - and _, 3 to 33 characters."
  type        = string
}

variable "project_id" {
  description = "Resource ID of the Foundry project that owns the connection."
  type        = string
}

variable "category" {
  description = "What the connection points at, such as AppInsights."
  type        = string
}

variable "target" {
  description = "Resource ID of the Azure resource the project connects to."
  type        = string
}

variable "api_version" {
  description = "API version of Microsoft.CognitiveServices/accounts/projects/connections."
  type        = string
}

variable "auth_type" {
  description = "How the project signs in to the target. AppInsights accepts only ProjectManagedIdentity or ApiKey; use ProjectManagedIdentity, which stores no key."
  type        = string
}

variable "extra_metadata" {
  description = "Extra metadata the target type requires, such as ApplicationInsightsConnectionString for AppInsights."
  type        = map(string)
  default     = {}
  sensitive   = true
}
