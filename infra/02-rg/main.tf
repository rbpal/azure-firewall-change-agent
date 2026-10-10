# Step 02: the workload resource group, and a budget that warns well before
# the $150 monthly credit runs out.

module "resource_group" {
  source = "../modules/resource-group"

  name     = var.resource_group_name
  location = var.location
  tags     = var.tags
}

module "budget" {
  source = "../modules/subscription-budget"

  name             = var.budget_name
  subscription_id  = data.azurerm_subscription.current.id
  amount           = var.budget_amount
  start_date       = var.budget_start_date
  alert_thresholds = var.budget_alert_thresholds
  contact_roles    = var.budget_contact_roles
}
