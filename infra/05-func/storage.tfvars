# Values for the function app's storage account. Each name is declared in variables.tf.

# Cost: Azure Storage has no free tier on this subscription. Standard LRS is
# the cheapest option, agreed 2026-10-10. It holds only the deployment
# package and Functions host data.
storage_name             = "stfwagentfuncdev"
storage_account_tier     = "Standard"
storage_replication_type = "LRS"

# Entra sign-in only. The function app uses its managed identity.
storage_shared_access_key_enabled = false

storage_package_container = "app-package"

# The tools read the network snapshot here; only the sync pipeline may write it.
# The app's Blob Data Owner role carries a condition that refuses every write,
# delete, tag or permission change in this container (security register 50.18).
storage_readonly_container = "network-snapshot"
