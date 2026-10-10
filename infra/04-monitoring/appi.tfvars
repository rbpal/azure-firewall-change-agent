# Values for Application Insights. Each name is declared in variables.tf.

appi_name             = "appi-fwagentic-dev"
appi_application_type = "web"

# Same cap as the workspace. The lower of the two caps wins.
appi_daily_data_cap_in_gb = 0.16

# Senders must sign in with Entra; the ingestion key alone is refused.
appi_local_authentication_disabled = true
