# Values for the platform logs (diagnostic settings) on the Foundry resource and
# project. Each name is declared in variables.tf.

# Built by step 04-monitoring: PerGB2018, 30-day retention, 0.16 GB daily cap.
# Application Insights stores its data in the same workspace, so platform logs
# and agent traces share that cap.
law_name = "law-fwagentic-dev"

diagnostic_setting_name = "diag-to-law-fwagentic-dev"

# Audit: who changed or read settings. RequestResponse: one row per API call
# (caller, operation, status, latency). Both are "Costs to export: No" in
# Microsoft's monitoring reference (checked 2026-10-15); only workspace
# ingestion applies, inside the free 5 GB a month.
# Left out: AzureOpenAIRequestUsage (export cost: Yes; token use per deployment
# is already free as platform metrics), Trace (overlaps the App Insights
# traces), ManagedNetworkEvent (no managed network).
foundry_account_log_categories = ["Audit", "RequestResponse"]

# The project offers Audit, Trace and AllMetrics. Audit only, for the same reasons.
foundry_project_log_categories = ["Audit"]
