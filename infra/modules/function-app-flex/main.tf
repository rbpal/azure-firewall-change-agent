resource "azurerm_function_app_flex_consumption" "this" {
  name                = var.name
  location            = var.location
  resource_group_name = var.resource_group_name
  service_plan_id     = var.service_plan_id

  runtime_name           = var.runtime_name
  runtime_version        = var.runtime_version
  instance_memory_in_mb  = var.instance_memory_in_mb
  maximum_instance_count = var.maximum_instance_count

  # The deployment package lives in blob storage, read with the app's own
  # identity. No storage key is used.
  storage_container_type      = "blobContainer"
  storage_container_endpoint  = var.storage_container_endpoint
  storage_authentication_type = "SystemAssignedIdentity"

  virtual_network_subnet_id = var.subnet_id

  https_only                                     = true
  webdeploy_publish_basic_authentication_enabled = false

  identity {
    type = "SystemAssigned"
  }

  app_settings = {
    # The Functions host reaches its storage with the managed identity.
    "AzureWebJobsStorage__accountName" = var.storage_account_name
    # Application Insights refuses the key, so the app signs in with Entra.
    "APPLICATIONINSIGHTS_AUTHENTICATION_STRING" = "Authorization=AAD"
  }

  site_config {
    application_insights_connection_string = var.application_insights_connection_string
    minimum_tls_version                    = "1.2"
  }

  tags = var.tags

  # Azure adds this tag to link the app to Application Insights in the portal.
  # It holds only a resource ID. Terraform leaves it alone so the plan stays
  # clean; every other tag is still managed here.
  lifecycle {
    ignore_changes = [
      tags["hidden-link: /app-insights-resource-id"],
    ]
  }
}
