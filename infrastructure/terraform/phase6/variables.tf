variable "deployment_approved" {
  type        = bool
  default     = false
  description = "Keep false until a cost-reviewed temporary deployment is explicitly approved."
}

variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "project_name" {
  type        = string
  default     = "smarttraffic-phase6"
  description = "Unique run-scoped prefix; use a fresh value for each temporary cloud test."

  validation {
    condition     = can(regex("^[a-z0-9-]{3,32}$", var.project_name))
    error_message = "project_name must be 3-32 lowercase letters, digits, or hyphens."
  }
}

variable "lambda_zip_path" {
  type        = string
  default     = "../../../.data/phase6/alert-service.zip"
  description = "ZIP built by scripts/build_phase6_lambda.py, relative to this module."
}
