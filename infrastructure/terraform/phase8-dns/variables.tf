variable "aws_region" {
  type    = string
  default = "ap-south-1"
}
variable "expected_account_id" {
  type    = string
  default = null
  validation {
    condition     = var.expected_account_id == null ? true : can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Expected account ID must contain exactly 12 digits."
  }
}

variable "domain_name" {
  type    = string
  default = "smarttrafficmgmt.online"
}

variable "public_api_hostname" {
  type    = string
  default = "api.smarttrafficmgmt.online"
}

variable "existing_hosted_zone_id" {
  type        = string
  default     = null
  nullable    = true
  description = "Reuse this public Route 53 hosted zone instead of creating one. Leave null to create the zone."
}

variable "certificate_enabled" {
  type        = bool
  default     = false
  description = "Keep false until Spaceship delegates the domain to the Route 53 nameservers from this state."
}
