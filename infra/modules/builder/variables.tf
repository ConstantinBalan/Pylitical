variable "output_bucket" {
  type        = string
  description = "S3 bucket the container publishes rendered output to."
}

variable "ssm_param_name" {
  type        = string
  default     = "/pylitical/gemini-api-key"
  description = "SSM parameter name for the Gemini API key."
}

variable "subnet_ids" {
  type        = list(string)
  description = "List of subnet IDs for the ECS task."
}
