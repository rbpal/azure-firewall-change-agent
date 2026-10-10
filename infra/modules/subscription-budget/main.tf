resource "azurerm_consumption_budget_subscription" "this" {
  name            = var.name
  subscription_id = var.subscription_id
  amount          = var.amount
  time_grain      = "Monthly"

  time_period {
    start_date = var.start_date
  }

  dynamic "notification" {
    for_each = var.alert_thresholds
    content {
      enabled        = true
      threshold      = notification.value
      threshold_type = "Actual"
      operator       = "GreaterThanOrEqualTo"
      contact_roles  = var.contact_roles
    }
  }
}
