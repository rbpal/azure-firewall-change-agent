# A connection from a Foundry project to another Azure resource. The project
# signs in as its own managed identity, so no key is stored. azurerm has no
# project-level connection resource yet, so this uses azapi.
resource "azapi_resource" "this" {
  type      = "Microsoft.CognitiveServices/accounts/projects/connections@${var.api_version}"
  name      = var.name
  parent_id = var.project_id

  # Azure requires auth type ProjectManagedIdentity for AppInsights connections
  # (its own error message, 2026-10-15), but the published schema does not list
  # that value, so azapi's schema check would refuse it. Azure still validates
  # the request: the AAD value was rejected with a 400.
  schema_validation_enabled = false

  body = {
    properties = merge({
      category = var.category
      target   = var.target
      authType = var.auth_type
      metadata = merge(var.target_is_resource ? {
        ApiType    = "Azure"
        ResourceId = var.target
      } : {}, var.extra_metadata)
    }, var.audience == null ? {} : { audience = var.audience })
  }
}
