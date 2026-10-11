# Variable names only. Values are set in one tfvars file per resource.

# ---- Shared values and lookups: values in plan-gate.tfvars

variable "resource_group_name" {
  description = "Workload resource group, built by step 02-rg. The identity lives here and reads it."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this step that takes tags."
  type        = map(string)
}

variable "state_resource_group_name" {
  description = "Resource group of the Terraform state account, built by the step 01 bootstrap."
  type        = string
}

variable "state_storage_account_name" {
  description = "The Terraform state account, built by the step 01 bootstrap."
  type        = string
}

variable "state_container_name" {
  description = "Container that holds every step's state file."
  type        = string
}

variable "state_blob_prefix" {
  description = "Only state blobs whose name starts with this may be read, such as envs- for the env-site roots."
  type        = string
}

# ---- Plan identity and its roles: values in uami.tfvars

variable "uami_name" {
  description = "Identity the pull request plan job signs in as."
  type        = string
}

variable "uami_resource_group_role" {
  description = "Role the plan identity holds on the workload resource group."
  type        = string
}

variable "uami_state_role" {
  description = "Role the plan identity holds on the state container, narrowed by the blob prefix."
  type        = string
}

# ---- Federated credential: values in fic.tfvars

variable "fic_name" {
  description = "Name of the trust rule on the plan identity."
  type        = string
}

variable "fic_issuer" {
  description = "Who signs the token the plan job presents."
  type        = string
}

variable "fic_subject" {
  description = "The exact repo and event the token must name."
  type        = string
}

variable "fic_audiences" {
  description = "Audiences the token must name."
  type        = list(string)
}
