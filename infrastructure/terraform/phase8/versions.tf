terraform {
  required_version = ">= 1.16.0"
  required_providers {
    aws  = { source = "hashicorp/aws", version = "~> 6.45" }
    helm = { source = "hashicorp/helm", version = "~> 2.17" }
    http = { source = "hashicorp/http", version = "~> 3.5" }
  }
}

provider "aws" {
  region = var.aws_region
}

data "aws_eks_cluster_auth" "main" {
  name       = aws_eks_cluster.main.name
  depends_on = [aws_eks_cluster.main]
}

provider "helm" {
  kubernetes {
    host                   = aws_eks_cluster.main.endpoint
    cluster_ca_certificate = base64decode(aws_eks_cluster.main.certificate_authority[0].data)
    token                  = data.aws_eks_cluster_auth.main.token
  }
}
