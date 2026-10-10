# The subscription comes from the ARM_SUBSCRIPTION_ID environment variable,
# never from a file in this repo. Resource providers are registered by the
# bootstrap step, so Terraform does not register any.
provider "azurerm" {
  features {}
  storage_use_azuread             = true
  resource_provider_registrations = "none"
}

# Entra ID objects: the tool server's app registration and its role
# assignments. The tenant comes from the az login session.
provider "azuread" {}
