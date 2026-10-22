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
  description = "Resource ID of the Azure resource the project connects to, or a URL when target_is_resource is false."
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

variable "target_is_resource" {
  description = "True when target is an Azure resource ID (adds ApiType and ResourceId metadata); false for a URL, such as an MCP server."
  type        = bool
  default     = true
}

variable "audience" {
  description = "Entra audience the project's identity requests a token for, such as an MCP server's Application ID URI. Null for none."
  type        = string
  default     = null
}
