# Values for the project's connection to Application Insights. Each name is
# declared in variables.tf.

# Built by step 04-monitoring. Local auth is off there, so ingestion is Entra only.
appi_name = "appi-fwagentic-dev"

# One AppInsights connection is allowed per project. Auth type
# ProjectManagedIdentity (set in main.tf): the project signs in with its own
# identity (uami-fwagentic-foundry-dev), and no key is stored in the connection. Cost: $0 for the connection; traces count against
# the 0.16 GB daily cap set in step 04.
appi_connection_name = "appi-fwagentic-dev"

# Newest GA version that azapi 2.13.0 knows (Azure itself lists up to
# 2026-09-01; checked 2026-10-15).
connection_api_version = "2026-05-01"
