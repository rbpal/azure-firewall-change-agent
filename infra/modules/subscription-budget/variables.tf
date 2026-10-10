variable "name" {
  description = "Name of the budget."
  type        = string
}

variable "subscription_id" {
  description = "Full resource ID of the subscription, in the form /subscriptions/<id>."
  type        = string
}

variable "amount" {
  description = "Monthly budget in the subscription's billing currency."
  type        = number
}

variable "start_date" {
  description = "First day of the first budget month, in RFC 3339 form, such as 2026-10-01T00:00:00Z. Azure requires the first day of a month."
  type        = string
}

variable "alert_thresholds" {
  description = "Percentages of the budget at which actual spend sends an alert."
  type        = list(number)
}

variable "contact_roles" {
  description = "Subscription roles whose members get the alert emails, such as Owner. Roles keep email addresses out of the code."
  type        = list(string)
}
