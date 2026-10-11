# Values for the sync identity. Each name is declared in variables.tf.
# Cost: user-assigned managed identities and role assignments are free.

uami_name = "uami-fwagentic-sync-dev"

# Write access to the snapshot container only, not the storage account.
uami_role = "Storage Blob Data Contributor"
