output "plan_identity_client_id" {
  description = "Client ID the plan gate signs in with. Store it as the AZURE_PLAN_CLIENT_ID repo secret in GitHub."
  value       = module.plan_identity.client_id
}
