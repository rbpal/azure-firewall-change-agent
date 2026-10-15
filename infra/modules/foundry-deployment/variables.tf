variable "name" {
  description = "Deployment name. Code calls the model by this name."
  type        = string
}

variable "foundry_id" {
  description = "Resource ID of the Foundry resource that hosts the deployment."
  type        = string
}

variable "model_name" {
  description = "OpenAI model name, such as gpt-6-luna."
  type        = string
}

variable "model_version" {
  description = "Pinned model version, so eval results always refer to the same model."
  type        = string
}

variable "sku_name" {
  description = "Deployment type, such as GlobalStandard (pay per token, processed in any region)."
  type        = string
}

variable "capacity" {
  description = "Units of throughput. One unit is 1,000 tokens and 1 request per minute."
  type        = number
}
