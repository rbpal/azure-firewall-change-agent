# Variable names only. Values are set in one tfvars file per resource.

# ---- Shared values and lookups: values in sync.tfvars

variable "resource_group_name" {
  description = "Workload resource group, built by step 02-rg. Every resource here takes its region."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this step that takes tags."
  type        = map(string)
}

variable "storage_account_name" {
  description = "The function app's storage account, built by step 05-func."
  type        = string
}

# ---- Blob container: values in container.tfvars

variable "container_name" {
  description = "Container that holds the copies of main the tools read."
  type        = string
}

# ---- Sync identity and its role: values in uami.tfvars

variable "uami_name" {
  description = "Identity the GitHub Actions sync job signs in as."
  type        = string
}

variable "uami_role" {
  description = "Role the sync identity holds on the container, and only there."
  type        = string
}

# ---- Federated credential: values in fic.tfvars

variable "fic_name" {
  description = "Name of the trust rule on the sync identity."
  type        = string
}

variable "fic_issuer" {
  description = "Who signs the token the sync job presents."
  type        = string
}

variable "fic_subject" {
  description = "The exact repo and branch the token must name."
  type        = string
}

variable "fic_audiences" {
  description = "Audiences the token must name."
  type        = list(string)
}

variable "blob_reader_for_terraform_user" {
  description = "Give the person running Terraform Storage Blob Data Reader on the whole storage account: every container, now and later."
  type        = bool
}
