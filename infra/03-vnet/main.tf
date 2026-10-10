# Step 03: the virtual network and its subnets.

module "vnet" {
  source = "../modules/vnet"

  name                = var.vnet_name
  location            = data.azurerm_resource_group.this.location
  resource_group_name = data.azurerm_resource_group.this.name
  address_space       = var.address_space
  tags                = var.tags
  subnets             = var.subnets
}
