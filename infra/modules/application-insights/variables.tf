variable "name" {
  description = "Name of the Application Insights resource."
  type        = string
}

variable "location" {
  description = "Azure region for Application Insights."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds Application Insights."
  type        = string
}

variable "workspace_id" {
  description = "Resource ID of the Log Analytics workspace that stores the data."
  type        = string
}

variable "application_type" {
  description = "Kind of application monitored, such as web or other."
  type        = string
}

variable "daily_data_cap_in_gb" {
  description = "Most data Application Insights takes in per day, in GB. The workspace cap also applies; the lower one wins."
  type        = number
}

variable "local_authentication_disabled" {
  description = "Whether the ingestion key is refused. True means senders must use Entra sign-in."
  type        = bool
}

variable "tags" {
  description = "Tags applied to Application Insights."
  type        = map(string)
}
