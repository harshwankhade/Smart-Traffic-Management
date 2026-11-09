# Phase 2 private SQL foundation - unapplied

Prepared configuration, **not deployed**. Terraform 1.16.1 and AWS provider 6.45.0 were used for validation and mocked tests. The provider is pinned and its lock file is retained. No AWS account query, real plan, apply or resource creation is part of these checks.

From project root:

```powershell
terraform -chdir=infrastructure/terraform/phase2 init -backend=false -input=false
terraform -chdir=infrastructure/terraform/phase2 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase2 validate
terraform -chdir=infrastructure/terraform/phase2 test
```

`init` downloads the signed provider and can need Internet access; it does not provision AWS resources. Both test runs explicitly use a mocked AWS provider and `command = plan`. One verifies the default approval guard fails; the other uses a test-only true value to inspect the proposed resources. No credentials are required for mocked tests. Do not run standalone `terraform plan` or `apply` under the current authorization.

The configuration defines one Mumbai VPC, two isolated database subnets with explicit empty route tables, an application identity security group and private database security group. Only TCP 5432 is allowed from the application group to the database. No Internet gateway, NAT, load balancer or app compute is created. Future authorized Kubernetes integration will extend networking and attach the application group appropriately; the current skeleton does not provide application/DNS/API egress.

RDS design: PostgreSQL major 17 (AWS selects an available compatible minor on creation), db.t4g.micro, 20 GiB gp3, single AZ, encryption, forced SSL, IAM authentication and RDS-managed master password. Only identifiers/endpoints are outputs. PostgreSQL bootstrapping and runtime roles are in [the SQL instructions](../../sql/README.md).

Before any deployment, verify actual region/AZ/instance/engine availability, IAM and RDS service-linked-role prerequisites, protected remote state, connectivity and a complete cost estimate within the US$5 cap. User acceptance of cost/access assumptions is not evidence they passed. RDS-managed secrets, backups and snapshots can add charges. Deletion protection and a final snapshot are intentionally enabled: a future teardown must explicitly review these settings and residual storage; nothing here authorizes destructive commands.
