terraform {
  backend "local" {}
  required_version = ">= 1.16.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.45"
    }
  }
}

provider "aws" {
  region              = var.aws_region
  allowed_account_ids = var.expected_account_id == null ? null : [var.expected_account_id]
}
