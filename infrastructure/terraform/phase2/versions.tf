terraform {
  required_version = ">= 1.7.0, < 2.0.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.45.0"
    }
  }
}

provider "aws" {
  region = "ap-south-1"
  default_tags {
    tags = {
      Project = var.project_name
      Phase   = "2"
    }
  }
}
