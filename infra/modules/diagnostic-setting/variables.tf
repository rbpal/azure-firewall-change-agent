variable "name" {
  description = "Name of the diagnostic setting, unique on the target resource."
  type        = string
}

variable "target_resource_id" {
  description = "Resource ID whose platform logs are sent."
  type        = string
}

variable "log_analytics_workspace_id" {
  description = "Resource ID of the Log Analytics workspace that receives the logs."
  type        = string
}

variable "log_categories" {
  description = "Log categories to send, such as Audit or RequestResponse. Each must be offered by the target resource."
  type        = list(string)
}
