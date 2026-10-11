# Step 08: the identity the pull request gate signs in as to run terraform plan.
#
# On every pull request, a GitHub Actions job signs in as this identity, with no
# secret, and plans each dev firewall policy. It can read, never write: Reader
# on the workload resource group, and blob read on the env-site state files only.
# Plan runs with -lock=false, so it needs no write on the state.

module "plan_identity" {
  source = "../modules/user-assigned-identity"

  name                = var.uami_name
  location            = data.azurerm_resource_group.this.location
  resource_group_name = data.azurerm_resource_group.this.name
  tags                = var.tags
}

module "plan_credential" {
  source = "../modules/federated-identity-credential"

  name        = var.fic_name
  identity_id = module.plan_identity.id
  issuer      = var.fic_issuer
  subject     = var.fic_subject
  audiences   = var.fic_audiences
}

# Read the firewall policies, IP groups and rule collection groups the plan compares against.
module "plan_reader" {
  source = "../modules/role-assignment"

  scope                = data.azurerm_resource_group.this.id
  role_definition_name = var.uami_resource_group_role
  principal_id         = module.plan_identity.principal_id
  principal_type       = "ServicePrincipal"
}

# Read the env-site state files only. The condition refuses any other blob in
# the container, such as the state of steps 02 to 08.
module "plan_state_reader" {
  source = "../modules/role-assignment"

  scope                = "${data.azurerm_storage_account.state.id}/blobServices/default/containers/${var.state_container_name}"
  role_definition_name = var.uami_state_role
  principal_id         = module.plan_identity.principal_id
  principal_type       = "ServicePrincipal"
  condition            = <<-EOT
    (
      (
        !(ActionMatches{'Microsoft.Storage/storageAccounts/blobServices/containers/blobs/read'} AND NOT SubOperationMatches{'Blob.List'})
      )
      OR
      (
        @Resource[Microsoft.Storage/storageAccounts/blobServices/containers/blobs:path] StringStartsWith '${var.state_blob_prefix}'
      )
    )
  EOT
}
