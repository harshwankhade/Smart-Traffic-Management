# Phase 8 integrated Terraform preparation

This root prepares one run-scoped deployment: EKS and Argo CD bootstrap, ECR repositories, a two-AZ VPC with NAT egress, MSK/S3/EMR modules, RDS PostgreSQL, DynamoDB, SQS/Lambda and an ACM-backed HTTPS ALB. It creates nothing with the default `deployment_approved=false`.

Before a plan that enables the guard, provide a unique run prefix, real administrator CIDRs, a public DNS name and its authoritative Route 53 zone. Build the EMR JAR and Lambda ZIP first. Terraform owns AWS infrastructure and the Argo CD bootstrap only; Step 3 will add GitOps-managed Kubernetes workloads.

Safe checks:

```powershell
terraform -chdir=infrastructure/terraform/phase8 init -backend=false -input=false
terraform -chdir=infrastructure/terraform/phase8 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase8 validate
.venv\Scripts\python scripts\phase8_package.py
```

An enabled review plan and later apply must use the same `project_name`, record the plan, and use a current cost preflight below the US$9.50 gate. Teardown removes the GitOps application through Git first, waits for Argo CD pruning, terminates EMR, empties only the state-owned versioned bucket, then runs `terraform destroy` and independent tagged-resource audits. Do not run apply or destroy in this step.
