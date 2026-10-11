# State for this env-site's firewall policy lives in the bootstrap storage
# account, under its own key, so a plan or apply here touches one policy only.
# Entra sign-in only: the account has shared keys turned off.
terraform {
  backend "azurerm" {
    resource_group_name  = "rg-terraform-state"
    storage_account_name = "stfwagentstaterbpal"
    container_name       = "tfstate"
    key                  = "envs-dev-centralus.tfstate"
    use_azuread_auth     = true
  }
}
