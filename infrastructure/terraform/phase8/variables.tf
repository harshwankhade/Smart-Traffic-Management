variable "deployment_approved" {
  default = false
}
variable "project_name" {
  default = "smarttraffic-phase8"
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
