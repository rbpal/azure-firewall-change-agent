# The firewall policy for dev-centralus, with its IP groups and rules.
# The demo builds the policy only, with no firewall attached (Demo deviations).

module "firewall_policy" {
  source = "../../modules/firewall-policy"

  name                = var.firewall_policy_name
  resource_group_name = data.azurerm_resource_group.this.name
  location            = var.location
  sku                 = var.firewall_policy_sku
  tags                = var.tags
  ip_groups           = var.ip_groups

  # Each rules file sets its own variable; they meet here as one map.
  rule_collection_groups = {
    hub  = var.hub
    ledg = var.ledg
    rprt = var.rprt
    sett = var.sett
    xfer = var.xfer
  }
}
