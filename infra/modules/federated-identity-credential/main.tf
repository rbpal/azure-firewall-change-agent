# Trust rule on a user-assigned managed identity: a token from the issuer, with
# exactly this subject, can sign in as the identity. No secret is stored.
resource "azurerm_federated_identity_credential" "this" {
  name                      = var.name
  user_assigned_identity_id = var.identity_id
  issuer                    = var.issuer
  subject                   = var.subject
  audience                  = var.audiences
}
