# Sends a resource's platform logs (Azure's own records about the resource,
# such as audit and request logs) to a Log Analytics workspace. This is a
# separate pipe from the agent traces that go through the project's
# Application Insights connection.
resource "azurerm_monitor_diagnostic_setting" "this" {
  name                       = var.name
  target_resource_id         = var.target_resource_id
  log_analytics_workspace_id = var.log_analytics_workspace_id

  dynamic "enabled_log" {
    for_each = toset(var.log_categories)
    content {
      category = enabled_log.value
    }
  }
}
