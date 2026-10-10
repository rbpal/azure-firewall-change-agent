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

  # Built-in auth checks every request before our code runs: a valid Entra
  # token for our API, from an allowed caller. Anything else gets a 401.
  # Only incoming tokens are validated, so no client secret is needed.
  dynamic "auth_settings_v2" {
    for_each = var.auth == null ? [] : [var.auth]

    content {
      auth_enabled           = true
      require_authentication = true
      unauthenticated_action = "Return401"
      default_provider       = "azureactivedirectory"
      require_https          = true

      active_directory_v2 {
        client_id            = auth_settings_v2.value.client_id
        tenant_auth_endpoint = auth_settings_v2.value.tenant_auth_endpoint
        allowed_audiences    = auth_settings_v2.value.allowed_audiences
        allowed_applications = auth_settings_v2.value.allowed_applications
      }

      login {
        token_store_enabled = false
      }
    }
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
