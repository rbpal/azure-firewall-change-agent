resource "azurerm_application_insights" "this" {
  name                          = var.name
  location                      = var.location
  resource_group_name           = var.resource_group_name
  workspace_id                  = var.workspace_id
  application_type              = var.application_type
  daily_data_cap_in_gb          = var.daily_data_cap_in_gb
  local_authentication_disabled = var.local_authentication_disabled
  tags                          = var.tags
}
