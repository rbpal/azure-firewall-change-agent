variable "app_role_id" {
  description = "ID of the app role to grant."
  type        = string
}

variable "principal_object_id" {
  description = "Object ID of the user or service principal that gets the role."
  type        = string
}

variable "resource_object_id" {
  description = "Object ID of the service principal (enterprise application) that defines the role."
  type        = string
}
