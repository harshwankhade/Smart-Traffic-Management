variable "deployment_approved" {
  type        = bool
  default     = false
  description = "Keep false. Explicit approval plus verified cost/access checks are required before any real resource planning."
}
variable "provision_database" {
  type        = bool
  default     = true
  description = "Keep true for Phase 2; a temporary Phase 4-only run can reuse networking without starting SQL."
}

variable "project_name" {
  type    = string
  default = "smarttraffic-phase2"
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,35}$", var.project_name)) && !endswith(var.project_name, "-") && !strcontains(var.project_name, "--")
    error_message = "Use 3-36 lowercase letters/digits/hyphens, starting with a letter, without trailing or doubled hyphens."
  }
}
