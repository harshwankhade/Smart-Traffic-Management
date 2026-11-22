# Reduced-startup integrated runtime

This guarded root provisions the VPC, two `t3.large` EKS workers by default (four for HPA validation), single-node EMR/Flink, RDS, DynamoDB, S3 runtime archive/checkpoints, SQS/Lambda, private Kafka DNS/trust, IAM and platform bootstrap. Argo CD deploys all application workloads, ZooKeeper, Kafka/internal NLB Service, monitoring and both HPAs. The runtime does not create MSK. ECR repositories are read from separately retained `phase8-artifacts` storage.

Read [the complete runbook](../../../docs/reduced-startup.md) and [approved decisions](../../../docs/decisions/reduced-startup.md), especially existing-state migration. Prepare binaries and publish/reuse images before runtime creation. No current runtime/cost state is inferred from old evidence or local Terraform files.

Safe local checks:

```powershell
terraform -chdir=infrastructure/terraform/phase8 init -backend=false -input=false
terraform -chdir=infrastructure/terraform/phase8 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase8 validate
terraform -chdir=infrastructure/terraform/phase8 test
.venv/Scripts/python scripts/phase8_gitops_check.py
```

Tests mock root AWS/Helm/TLS resources and stub legacy child-module outputs; child modules have separate mock tests. `deployment_approved=false` remains default. AWS-backed plans/applies, image/binary publication, state migration, Git publication and teardown require the applicable authorization. Protect Terraform state: it contains the generated Kafka private key, which must never appear in logs or Git.

The new cloud shape, private NLB/DNS connectivity and demo and HPA capacity remain unverified until a separately authorized run. Retain artifact and public DNS/certificate state during approved runtime cleanup; audit controller-created ALB/NLB groups and EBS volumes too.
