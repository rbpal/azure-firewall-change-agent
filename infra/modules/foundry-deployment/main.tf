# One model deployment on a Foundry resource. Capacity is in units: one unit
# is 1,000 tokens and 1 request per minute, so a small capacity caps spend.
resource "azurerm_cognitive_deployment" "this" {
  name                   = var.name
  cognitive_account_id   = var.foundry_id
  version_upgrade_option = "NoAutoUpgrade"

  model {
    format  = "OpenAI"
    name    = var.model_name
    version = var.model_version
  }

  sku {
    name     = var.sku_name
    capacity = var.capacity
  }
}
