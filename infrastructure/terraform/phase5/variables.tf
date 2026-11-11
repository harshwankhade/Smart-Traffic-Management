variable "deployment_approved" {
  type        = bool
  default     = false
  description = "Keep false until a reviewed, temporary DynamoDB verification is explicitly approved."
}

variable "aws_region" {
  type    = string
  default = "ap-south-1"
}

variable "project_name" {
  type        = string
  default     = "smarttraffic-phase5"
  description = "Run-scoped prefix for the only two DynamoDB tables and two policies."

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]{3,64}$", var.project_name))
    error_message = "project_name must be 3-64 letters, digits, periods, underscores, or hyphens."
  }
}
