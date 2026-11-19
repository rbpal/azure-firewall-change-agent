# One Azure Monitor workbook: a saved page of queries and charts. It stores no
# data of its own; it reads its source resource each time someone opens it.
resource "azurerm_application_insights_workbook" "this" {
  name                = var.name
  resource_group_name = var.resource_group_name
  location            = var.location
  display_name        = var.display_name
  description         = var.description
  category            = "workbook"
  source_id           = var.source_id
  data_json           = var.data_json
  tags                = var.tags
}
