# Phase 4 Amazon EMR on EC2 module

This is the current Phase 4 processing module. It prepares a private Amazon EMR 7.14 cluster
running Flink 1.20, not Amazon Managed Service for Apache Flink. The cluster consumes the existing
private two-broker MSK input topic, writes `traffic.results`, stores its JAR, logs, checkpoints and
verification markers in the existing private Phase 3 S3 bucket, and reuses the Phase 2 network.

The module does not create a second VPC, a database, NAT gateway, EKS cluster or public endpoint.
`deployment_approved` defaults to `false`; an ordinary plan fails until a specifically authorized
run deliberately enables it. Terraform remains the owner of all resources.

## IAM and network boundaries

The EMR service role has AWS-managed `AmazonEMRServicePolicy_v2` plus one inline permission:
`iam:PassRole` for this module's exact custom EC2 role, only when passed to `ec2.amazonaws.com`.
The AWS-managed policy covers only the conventional `EMR_EC2_DefaultRole`, so the inline grant is
required for the custom run-scoped role. Do not broaden it to `Resource = "*"`.

The VPC, isolated subnets, EMR cluster and EMR security groups carry
`for-use-with-amazon-emr-managed-policies = true`. Traffic is limited to private EMR control-plane
rules, MSK IAM/TLS on 9098, and S3 through the existing gateway endpoint. The three EMR security
groups set `revoke_rules_on_delete = true`, allowing Terraform to remove rules that EMR adds before
deleting only the security-group IDs already recorded in the current run's state.

## Local validation and mocked tests

Build the EMR artifact first, then run:

```powershell
mvn -f services/congestion-processor/pom.xml -P emr package
terraform -chdir=infrastructure/terraform/phase4 init -backend=false -input=false
terraform -chdir=infrastructure/terraform/phase4 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase4 validate
terraform -chdir=infrastructure/terraform/phase4 test
```

The Terraform tests mock AWS. They verify the disabled deployment guard, EMR 7.14/Flink placement,
two-node topology, distinct two-replica result topic, private security-group paths, scoped role
passing and state-owned security-group cleanup behavior.

## Reviewed composite plan and teardown

The temporary composite root is `../phase4-live`. After the separate deployment preflight and
explicit authorization, its plan-only command is:

```powershell
.venv\Scripts\python scripts\run_phase4_cloud.py --plan-only
```

Plan-only creates no AWS resources and records the reviewed changes in
`.data/phase4-cloud/reviewed-plan.json` plus `docs/evidence/phase-4-plan.json`. Never run
`terraform apply` manually. A later authorized managed test must use the runner so its `finally`
path terminates the state-recorded EMR cluster, empties only the state-recorded run bucket, lets
Terraform revoke rules/delete resources from its own state, and verifies that state is empty.
Retain the state and run variables until independent cleanup succeeds.

Formatting, validation, mocked tests and a plan alone do not prove cloud behavior. The separately
authorized temporary run `stp4-91dd0a43a8` subsequently proved EMR 7.14/Flink 1.20 submission,
private MSK input/results, S3 checkpoint recovery and Terraform teardown. Both EMR steps completed;
the independent AWS audit found no run-owned resources afterward. See the
[composite runbook](../phase4-live/README.md), [managed result](../../../docs/evidence/phase-4-cloud.json)
and [cleanup audit](../../../docs/evidence/phase-4-cleanup.json). The run tested this configuration
once; future regional capacity and actual billed cost against the US$10 cap are not established.
The deployment guard is disabled, and any new apply requires separate authorization.
