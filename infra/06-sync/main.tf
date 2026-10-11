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
