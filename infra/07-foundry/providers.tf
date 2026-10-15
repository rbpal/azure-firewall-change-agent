# The subscription comes from the ARM_SUBSCRIPTION_ID environment variable,
# never from a file in this repo. Resource providers are registered by the
# bootstrap step, so Terraform does not register any.
provider "azurerm" {
  features {}
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

# azapi signs in the same way as azurerm (az login locally, ARM_SUBSCRIPTION_ID).
provider "azapi" {}
