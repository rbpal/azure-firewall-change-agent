# Values for the virtual network and its subnets. Each name is declared in variables.tf.

resource_group_name = "rg-fwagentic-dev"
vnet_name           = "vnet-fwagentic-dev"
address_space       = ["10.60.0.0/20"]

tags = {
  project    = "azure-firewall-change-agent"
  env        = "dev"
  managed_by = "terraform"
  step       = "03-vnet"
}

# The demo creates one subnet. The Function app joins it so the DNS tool can
# reach Azure DNS at 168.63.129.16. Flex Consumption needs the subnet
# delegated to Microsoft.App/environments.
#
# Reserved, not created in the demo (enterprise design only):
#   10.60.0.0/26    AzureFirewallSubnet
#   10.60.0.64/26   AzureFirewallManagementSubnet
#   10.60.0.128/26  AzureBastionSubnet
#   10.60.0.192/26  snet-pep-dev
#   10.60.1.0/25    snet-compute-dev
subnets = {
  "snet-func-dev" = {
    address_prefixes = ["10.60.1.128/26"]
    delegation = {
      name         = "flex-consumption"
      service_name = "Microsoft.App/environments"
      actions      = ["Microsoft.Network/virtualNetworks/subnets/join/action"]
    }
  }
}
