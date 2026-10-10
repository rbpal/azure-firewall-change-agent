# Variable names only. Values are set in one tfvars file per resource.

# ---- Function app, plus shared values and lookups: values in func.tfvars

variable "resource_group_name" {
  description = "Workload resource group, built by step 02-rg. Every resource here takes its region."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this step."
  type        = map(string)
}

variable "vnet_name" {
  description = "Virtual network built by step 03-vnet."
  type        = string
}

variable "subnet_name" {
  description = "Delegated subnet the function app joins, built by step 03-vnet."
  type        = string
}

variable "appi_name" {
  description = "Application Insights built by step 04-monitoring."
  type        = string
}

variable "func_name" {
  description = "Name of the function app."
  type        = string
}

variable "func_runtime_name" {
  description = "Language runtime of the function app."
  type        = string
}

variable "func_runtime_version" {
  description = "Runtime version of the function app."
  type        = string
}

variable "func_instance_memory_in_mb" {
  description = "Memory per instance in MB."
  type        = number
}

variable "func_maximum_instance_count" {
  description = "Most instances the function app may scale out to."
  type        = number
}

# ---- Storage account: values in storage.tfvars

variable "storage_name" {
  description = "Name of the function app's storage account."
  type        = string
}

variable "storage_account_tier" {
  description = "Performance tier of the storage account."
  type        = string
}

variable "storage_replication_type" {
  description = "Replication of the storage account."
  type        = string
}

variable "storage_shared_access_key_enabled" {
  description = "Whether the storage account accepts keys."
  type        = bool
}

variable "storage_package_container" {
  description = "Blob container that holds the function app's deployment package."
  type        = string
}

# ---- Hosting plan: values in plan.tfvars

variable "plan_name" {
  description = "Name of the hosting plan."
  type        = string
}

variable "plan_os_type" {
  description = "Operating system of the hosting plan."
  type        = string
}

variable "plan_sku_name" {
  description = "SKU of the hosting plan."
  type        = string
}

# ---- Tool server app registration: values in entra.tfvars

variable "mcp_app_name" {
  description = "Display name of the app registration that callers request tokens for."
  type        = string
}

variable "mcp_app_role_value" {
  description = "App role a caller must hold to call the tools. Appears in the token's roles claim."
  type        = string
}

variable "mcp_app_role_description" {
  description = "What the app role allows."
  type        = string
}

variable "mcp_test_clients" {
  description = "Names from Microsoft's published app list, such as MicrosoftAzureCli, allowed to get a token as a signed-in person and call the tools."
  type        = list(string)
}

variable "mcp_role_for_terraform_user" {
  description = "Whether the person running Terraform gets the app role, so they can test the tools from a laptop."
  type        = bool
}

# ---- Caller identity: values in uami.tfvars

variable "uami_name" {
  description = "User-assigned managed identity that Foundry Agent Service signs in as to call the tools."
  type        = string
}
