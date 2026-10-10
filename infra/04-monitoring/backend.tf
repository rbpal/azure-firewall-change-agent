# State for this step lives in the bootstrap storage account, under its own key.
# Entra sign-in only: the account has shared keys turned off.
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-terraform-state"
    storage_account_name = "stfwagentstaterbpal"
    container_name       = "tfstate"
    key                  = "04-monitoring.tfstate"
    use_azuread_auth     = true
  }
}
