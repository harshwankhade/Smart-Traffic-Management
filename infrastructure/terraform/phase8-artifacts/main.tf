terraform {
  backend "local" {}
  required_version = ">= 1.16.0"
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.45" }
  }
}
provider "aws" {
  region              = var.aws_region
  allowed_account_ids = var.expected_account_id == null ? null : [var.expected_account_id]
}
variable "expected_account_id" {
  type    = string
  default = null
  validation {
    condition     = var.expected_account_id == null ? true : can(regex("^[0-9]{12}$", var.expected_account_id))
    error_message = "Expected account ID must contain exactly 12 digits."
  }
}
variable "aws_region" { default = "ap-south-1" }
variable "project_name" { default = "smarttraffic-phase8" }
variable "deployment_approved" { default = false }
resource "terraform_data" "deployment_guard" {
  lifecycle {
    precondition {
      condition     = var.deployment_approved
      error_message = "Retained artifact storage requires separate reviewed deployment approval."
    }
  }
}
locals {
  services = toset(["sensor-registry", "traffic-ingestion", "event-publisher", "signal-recommendation", "incident-manager", "traffic-analytics"])
  tags     = { Project = "SmartTraffic", ManagedBy = "Terraform", Purpose = "RetainedBuildArtifacts" }
}
resource "aws_ecr_repository" "services" {
  for_each             = local.services
  name                 = "${var.project_name}/${each.key}"
  image_tag_mutability = "IMMUTABLE"
  force_delete         = false
  image_scanning_configuration { scan_on_push = true }
  tags       = local.tags
  depends_on = [terraform_data.deployment_guard]
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket" "builds" {
  bucket_prefix = "${var.project_name}-builds-"
  force_destroy = false
  tags          = local.tags
  depends_on    = [terraform_data.deployment_guard]
  lifecycle { prevent_destroy = true }
}
resource "aws_s3_bucket_public_access_block" "builds" {
  bucket                  = aws_s3_bucket.builds.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
resource "aws_s3_bucket_server_side_encryption_configuration" "builds" {
  bucket = aws_s3_bucket.builds.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}
resource "aws_s3_bucket_versioning" "builds" {
  bucket = aws_s3_bucket.builds.id
  versioning_configuration { status = "Enabled" }
}
resource "aws_s3_bucket_policy" "builds" {
  bucket = aws_s3_bucket.builds.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Deny", Principal = "*", Action = "s3:*",
    Resource  = [aws_s3_bucket.builds.arn, "${aws_s3_bucket.builds.arn}/*"],
    Condition = { Bool = { "aws:SecureTransport" = "false" } }
  }] })
}
output "ecr_repositories" { value = { for name, repo in aws_ecr_repository.services : name => repo.repository_url } }
output "build_bucket" { value = aws_s3_bucket.builds.id }
