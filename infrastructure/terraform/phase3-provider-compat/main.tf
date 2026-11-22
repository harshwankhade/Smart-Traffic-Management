# Provider-address compatibility only. No cloud resources are declared here.
# Existing Phase 8 state may still refer to module.streaming's legacy provider
# while moved blocks adopt its archive or a reviewed plan retires old MSK.
terraform {
  required_providers {
    aws = { source = "hashicorp/aws", version = "~> 6.45" }
  }
}
provider "aws" { region = "ap-south-1" }
