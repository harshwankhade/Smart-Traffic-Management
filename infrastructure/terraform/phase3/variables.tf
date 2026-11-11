variable "deployment_approved" {
  type    = bool
  default = false
}

variable "project_name" {
  type    = string
  default = "smarttraffic-phase3"
}

variable "vpc_id" {
  type        = string
  description = "Existing Phase 2 vpc_id output; do not invent an account resource."
}

variable "private_subnet_ids" {
  type = list(string)
  validation {
    condition     = length(distinct(var.private_subnet_ids)) == 2
    error_message = "Supply exactly two existing private subnet IDs across two AZs."
  }
}

variable "private_route_table_ids" {
  type        = list(string)
  description = "Existing Phase 2 private route table IDs for the S3 gateway endpoint."
}

variable "application_security_group_id" {
  type = string
}
