# Variable names only. Values are set in one tfvars file per resource.

# ---- Resource group: values in rg.tfvars

variable "location" {
  description = "Azure region for the workload resources."
  type        = string
}

variable "resource_group_name" {
  description = "Name of the workload resource group that holds every project resource."
  type        = string
}

variable "tags" {
  description = "Tags applied to every resource in this step."
  type        = map(string)
}

# ---- Subscription budget: values in budget.tfvars

variable "budget_name" {
  description = "Name of the subscription budget."
  type        = string
}

variable "budget_amount" {
  description = "Monthly budget in US dollars."
  type        = number
}

variable "budget_start_date" {
  description = "First day of the first budget month, such as 2026-10-01T00:00:00Z."
  type        = string
}

variable "budget_alert_thresholds" {
  description = "Percentages of the budget at which actual spend sends an alert."
  type        = list(number)
}

variable "budget_contact_roles" {
  description = "Subscription roles whose members get the budget alert emails."
  type        = list(string)
}
