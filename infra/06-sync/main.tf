# Step 06: the copy of main that the agent's tools read.
#
# On every push to main, a GitHub Actions job signs in as the sync identity,
# with no secret, and copies the network data and rules files into the
# container. The function app reads them with its own managed identity.

module "container" {
  source = "../modules/storage-container"

  name               = var.container_name
  storage_account_id = data.azurerm_storage_account.func.id
}

module "sync_identity" {
  source = "../modules/user-assigned-identity"

  name                = var.uami_name
  location            = data.azurerm_resource_group.this.location
  resource_group_name = data.azurerm_resource_group.this.name
  tags                = var.tags
}

module "sync_credential" {
  source = "../modules/federated-identity-credential"

  name        = var.fic_name
  identity_id = module.sync_identity.id
  issuer      = var.fic_issuer
  subject     = var.fic_subject
  audiences   = var.fic_audiences
}

module "sync_role" {
  source = "../modules/role-assignment"

  scope                = module.container.id
  role_definition_name = var.uami_role
  principal_id         = module.sync_identity.principal_id
  principal_type       = "ServicePrincipal"
}

# Read-only view of every container in the storage account for the person
# running Terraform: the snapshots, the deployed app package and the Functions
# host's own containers, including any created later (decided 2026-10-22).
# Owner manages the account but reads no blobs, and shared keys are off.
# Read only: this role can never upload, change or delete a blob. It can read
# azure-webjobs-secrets, which holds the Functions host keys.
module "terraform_user_blob_reader" {
  source = "../modules/role-assignment"
  count  = var.blob_reader_for_terraform_user ? 1 : 0

  scope                = data.azurerm_storage_account.func.id
  role_definition_name = "Storage Blob Data Reader"
  principal_id         = data.azurerm_client_config.current.object_id
  principal_type       = "User"
}
