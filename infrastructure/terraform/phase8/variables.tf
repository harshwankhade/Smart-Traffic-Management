variable "deployment_approved" {
  default = false
}
variable "gitops_bootstrap_enabled" {
  type        = bool
  default     = true
  description = "Keep false during initial infrastructure provisioning until the new digest-pinned GitOps revision is published."
}
variable "expected_account_id" {
  type        = string
  default     = null
  description = "Optional account boundary; account-switch tooling always supplies it."
  validation {
    condition     = var.expected_account_id == null ? true : can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Expected account ID must contain exactly 12 digits."
  }
}
variable "project_name" {
  default = "smarttraffic-phase8"
}
variable "eks_worker_count" {
  type        = number
  default     = 2
  description = "Two t3.large workers for the light demo; four for full HPA validation. No node autoscaler is configured."
  validation {
    condition     = contains([2, 4], var.eks_worker_count)
    error_message = "Choose two demo workers or four HPA-validation workers."
  }
}
variable "aws_region" {
  default = "ap-south-1"
}
variable "availability_zones" {
  default = ["ap-south-1a", "ap-south-1b"]
}
variable "admin_cidrs" { type = list(string) }
variable "public_dns_name" { type = string }
variable "route53_zone_id" { type = string }
variable "public_certificate_arn" {
  type        = string
  description = "ACM certificate ARN from the separately managed phase8-dns state."
}
variable "git_repository_url" {
  type    = string
  default = "https://github.com/harshwankhade/Smart-Traffic-Management.git"
}
variable "lambda_zip_path" {
  default = "../../../.data/phase6/alert-service.zip"
}
variable "emr_jar_path" {
  default = "../../../services/congestion-processor/target-emr/congestion-processor-1.0.0.jar"
}
