# One model deployment on a Foundry resource. Capacity is a throughput limit in
# units: one unit allows 1,000 tokens and 1 request per minute. Billing is per
# token, so capacity does not cap spend.
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
