# Grants an Entra app role, such as Tools.Read, to a user or service principal.
resource "azuread_app_role_assignment" "this" {
  app_role_id         = var.app_role_id
  principal_object_id = var.principal_object_id
  resource_object_id  = var.resource_object_id
}
