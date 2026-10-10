# Values for the Log Analytics workspace, plus the two values both resources
# share. Each name is declared in variables.tf.

resource_group_name = "rg-fwagentic-dev"

tags = {
  project    = "azure-firewall-change-agent"
  env        = "dev"
  managed_by = "terraform"
  step       = "04-monitoring"
}

log_name              = "law-fwagentic-dev"
log_sku               = "PerGB2018"
log_retention_in_days = 30

# The first 5 GB a month is free per billing account. 0.16 GB a day is about
# 4.8 GB a month, so the workspace stops taking data before it costs money.
log_daily_quota_gb = 0.16

# Entra sign-in only, no shared keys.
log_local_authentication_enabled = false
