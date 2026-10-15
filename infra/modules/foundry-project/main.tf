# A Foundry project inside a Foundry resource. Agents, connections and
# evaluation runs live here. It signs in as the user-assigned identity given.
resource "azurerm_cognitive_account_project" "this" {
  name                 = var.name
  cognitive_account_id = var.foundry_id
  location             = var.location
  display_name         = var.display_name
  description          = var.description
  tags                 = var.tags

  identity {
    type         = "UserAssigned"
    identity_ids = [var.identity_id]
  }
}
