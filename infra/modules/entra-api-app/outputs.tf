output "client_id" {
  description = "Application (client) ID of the app registration."
  value       = azuread_application.this.client_id
}

output "identifier_uri" {
  description = "Application ID URI, api://<client id>. Callers use it as the token audience."
  value       = azuread_application_identifier_uri.this.identifier_uri
}

output "service_principal_object_id" {
  description = "Object ID of the service principal (enterprise application). Role assignments point at it."
  value       = azuread_service_principal.this.object_id
}

output "app_role_id" {
  description = "ID of the app role."
  value       = random_uuid.app_role.result
}
