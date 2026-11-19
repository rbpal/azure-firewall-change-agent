variable "name" {
  description = "Workbook name. Azure requires a GUID; the root derives a fixed one with uuidv5()."
  type        = string
}

variable "resource_group_name" {
  description = "Resource group that holds the workbook."
  type        = string
}

variable "location" {
  description = "Azure region for the workbook."
  type        = string
}

variable "display_name" {
  description = "Name shown in the portal."
  type        = string
}

variable "description" {
  description = "One sentence shown under the name in the portal."
  type        = string
}

variable "source_id" {
  description = "Resource the workbook opens against, lower case as the provider requires."
  type        = string
}

variable "data_json" {
  description = "The workbook definition (Notebook/1.0 JSON)."
  type        = string
}

variable "tags" {
  description = "Tags applied to the workbook."
  type        = map(string)
}
