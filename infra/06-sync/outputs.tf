output "container_name" {
  description = "Container that holds the copies of main."
  value       = module.container.name
}

output "sync_identity_client_id" {
  description = "Client ID the sync job signs in with. Set it as the AZURE_CLIENT_ID repo variable in GitHub."
  value       = module.sync_identity.client_id
}
