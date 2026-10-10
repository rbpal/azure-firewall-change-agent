output "function_app_name" {
  description = "Name of the function app."
  value       = module.func.name
}

output "function_app_hostname" {
  description = "Host name of the function app."
  value       = module.func.default_hostname
}

output "function_app_principal_id" {
  description = "Object ID of the function app's managed identity. Later steps grant it read roles."
  value       = module.func.principal_id
}

output "storage_account_name" {
  description = "Name of the function app's storage account."
  value       = module.storage.name
}

output "mcp_api_identifier_uri" {
  description = "Audience callers request tokens for. Foundry's MCP connection uses it in Step 03."
  value       = module.mcp_api.identifier_uri
}

output "mcp_endpoint" {
  description = "MCP endpoint served by the Functions MCP extension."
  value       = "https://${module.func.default_hostname}/runtime/webhooks/mcp"
}

output "caller_identity_client_id" {
  description = "Client ID of the identity Foundry signs in as. On the function app's allow list."
  value       = module.caller_identity.client_id
}

output "caller_identity_id" {
  description = "Resource ID of the identity, for attaching it to the Foundry project in Step 03."
  value       = module.caller_identity.id
}
