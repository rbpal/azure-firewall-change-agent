# The tool server's front door in Entra ID: an app registration that callers
# request tokens for, one app role they must hold, and its service principal
# (enterprise application), which holds the role assignments.

resource "random_uuid" "app_role" {}

resource "random_uuid" "scope" {}

resource "azuread_application" "this" {
  display_name     = var.display_name
  sign_in_audience = "AzureADMyOrg"
  owners           = var.owners

  api {
    # v2 tokens: issuer is login.microsoftonline.com/<tenant>/v2.0.
    requested_access_token_version = 2

    # Delegated scope. Only a signed-in person's token uses it, and only
    # pre-authorized test clients can request it. Services use the app role.
    oauth2_permission_scope {
      id                         = random_uuid.scope.result
      value                      = "user_impersonation"
      type                       = "User"
      enabled                    = true
      admin_consent_display_name = "Call ${var.display_name}"
      admin_consent_description  = "Call the tools on ${var.display_name} as the signed-in user."
      user_consent_display_name  = "Call ${var.display_name}"
      user_consent_description   = "Call the tools on ${var.display_name} as you."
    }
  }

  app_role {
    id                   = random_uuid.app_role.result
    value                = var.app_role_value
    display_name         = var.app_role_value
    description          = var.app_role_description
    allowed_member_types = ["Application", "User"]
    enabled              = true
  }

  # The api://<client id> URI is set by azuread_application_identifier_uri
  # below, because it needs the client ID this resource creates.
  lifecycle {
    ignore_changes = [identifier_uris]
  }
}

resource "azuread_application_identifier_uri" "this" {
  application_id = azuread_application.this.id
  identifier_uri = "api://${azuread_application.this.client_id}"
}

# Assignment required: Entra issues a token only to identities that hold an
# app role on this service principal.
resource "azuread_service_principal" "this" {
  client_id                    = azuread_application.this.client_id
  app_role_assignment_required = true
  owners                       = var.owners
}

# Clients allowed to request the delegated scope without a consent prompt,
# such as Azure CLI for tests from a laptop.
resource "azuread_application_pre_authorized" "this" {
  for_each = toset(var.pre_authorized_client_ids)

  application_id       = azuread_application.this.id
  authorized_client_id = each.value
  permission_ids       = [random_uuid.scope.result]
}
