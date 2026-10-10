# Values for the subscription budget. Each name is declared in variables.tf.

budget_name             = "budget-fwagentic-monthly"
budget_amount           = 100
budget_start_date       = "2026-10-01T00:00:00Z"
budget_alert_thresholds = [50, 80, 100]
budget_contact_roles    = ["Owner"]
