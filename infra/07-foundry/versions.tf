terraform {
  required_version = ">= 1.14.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 4.0"
    }
    # Only for Foundry features azurerm does not cover yet (project connections).
    azapi = {
      source  = "azure/azapi"
      version = "~> 2.0"
    }
  }
}
