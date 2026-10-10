output "log_analytics_id" {
  description = "Resource ID of the Log Analytics workspace."
  value       = module.log_analytics.id
}

output "application_insights_id" {
  description = "Resource ID of Application Insights."
  value       = module.application_insights.id
}

output "application_insights_name" {
  description = "Name of Application Insights. Later steps look it up by this name."
  value       = module.application_insights.name
}
