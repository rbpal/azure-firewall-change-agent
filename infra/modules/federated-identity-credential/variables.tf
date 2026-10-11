variable "name" {
  description = "Name of the federated credential. Unique on its identity."
  type        = string
}

variable "identity_id" {
  description = "Resource ID of the user-assigned managed identity that trusts the token."
  type        = string
}

variable "issuer" {
  description = "Who signs the token, such as https://token.actions.githubusercontent.com for GitHub Actions."
  type        = string
}

variable "subject" {
  description = "The exact subject the token must carry, such as repo:<owner>@<owner-id>/<repo>@<repo-id>:ref:refs/heads/main as GitHub now issues it."
  type        = string
}

variable "audiences" {
  description = "Audiences the token must name. Entra expects api://AzureADTokenExchange."
  type        = list(string)
}
