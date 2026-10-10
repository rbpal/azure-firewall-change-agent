variable "name" {
  description = "Name of the function app. Also its host name, so unique across Azure."
  type        = string
}

variable "location" {
  description = "Azure region for the function app."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the function app."
  type        = string
}

variable "service_plan_id" {
  description = "Resource ID of the Flex Consumption plan."
  type        = string
}

variable "runtime_name" {
  description = "Language runtime, such as python."
  type        = string
}

variable "runtime_version" {
  description = "Runtime version, such as 3.11."
  type        = string
}

variable "instance_memory_in_mb" {
  description = "Memory per instance in MB. Smaller instances use the free GB-second grant more slowly."
  type        = number
}

variable "maximum_instance_count" {
  description = "Most instances the app may scale out to. Limits the cost of a runaway."
  type        = number
}

variable "storage_container_endpoint" {
  description = "Blob container URL that holds the deployment package."
  type        = string
}

variable "storage_account_name" {
  description = "Storage account the Functions host uses, reached with the app's managed identity."
  type        = string
}

variable "subnet_id" {
  description = "Delegated subnet the app joins for VNet integration."
  type        = string
}

variable "application_insights_connection_string" {
  description = "Connection string of Application Insights. With local auth off, the app signs in with its identity."
  type        = string
  sensitive   = true
}

variable "tags" {
  description = "Tags applied to the function app."
  type        = map(string)
}

variable "auth" {
  description = "Built-in Entra auth. client_id: the API's app registration. tenant_auth_endpoint: https://login.microsoftonline.com/<tenant>/v2.0. allowed_audiences: token audiences accepted. allowed_applications: caller client IDs accepted. Null turns built-in auth off."
  type = object({
    client_id            = string
    tenant_auth_endpoint = string
    allowed_audiences    = list(string)
    allowed_applications = list(string)
  })
  default = null
}
