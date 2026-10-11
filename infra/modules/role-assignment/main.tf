resource "azurerm_role_assignment" "this" {
  scope                = var.scope
  role_definition_name = var.role_definition_name
  principal_id         = var.principal_id
  principal_type       = var.principal_type

  # Optional attribute-based condition, such as "only blobs whose name starts
  # with envs-". Left null, the role applies to the whole scope as before.
  condition         = var.condition
  condition_version = var.condition == null ? null : "2.0"
}
