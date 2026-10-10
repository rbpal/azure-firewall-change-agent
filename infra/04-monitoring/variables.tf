# Variable names only. Values are set in one tfvars file per resource.

# ---- Shared: value in log.tfvars

variable "resource_group_name" {
  description = "Workload resource group, built by step 02-rg. Both resources take its region."
  type        = string
}

variable "tags" {
  description = "Tags applied to both resources in this step."
  type        = map(string)
}

# ---- Log Analytics workspace: values in log.tfvars

variable "log_name" {
  description = "Name of the Log Analytics workspace."
  type        = string
}

variable "log_sku" {
  description = "Pricing tier of the workspace."
  type        = string
}

variable "log_retention_in_days" {
  description = "Days the workspace keeps data."
  type        = number
}

variable "log_daily_quota_gb" {
  description = "Most data the workspace takes in per day, in GB."
  type        = number
}

variable "log_local_authentication_enabled" {
  description = "Whether the workspace accepts shared keys."
  type        = bool
}

# ---- Application Insights: values in appi.tfvars

variable "appi_name" {
  description = "Name of the Application Insights resource."
  type        = string
}

variable "appi_application_type" {
  description = "Kind of application monitored."
  type        = string
}

variable "appi_daily_data_cap_in_gb" {
  description = "Most data Application Insights takes in per day, in GB."
  type        = number
}

variable "appi_local_authentication_disabled" {
  description = "Whether Application Insights refuses the ingestion key."
  type        = bool
}
