# Phase 5 guarded DynamoDB module

This Terraform root defines only two temporary, on-demand DynamoDB tables and two
unattached least-privilege IAM policies. Signal Recommendation owns
`<run>-recommendations`; Traffic Analytics owns `<run>-summaries`. Both use the approved
`intersection_id` partition key and `window_key` sort key, encrypted server-side with an
AWS-owned key. No index, stream, backup, VPC, EKS, MSK, Lambda, role attachment, alert
table, or recovery-event resource is included.

The default `deployment_approved=false` guard makes an ordinary real plan fail. The mocked
test deliberately sets it true only under Terraform's mock AWS provider. The service policies
grant just `DescribeTable`, `GetItem`, `PutItem`, and `Query` on their own table; the module
does not attach either policy to a workload identity because that deployment identity is out
of this narrowly scoped verification.

Safe local checks, which create no AWS resource:

```powershell
terraform -chdir=infrastructure/terraform/phase5 init -backend=false -input=false
terraform -chdir=infrastructure/terraform/phase5 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase5 validate
terraform -chdir=infrastructure/terraform/phase5 test
```

The mocked checks prove that the guard rejects default planning and that the enabled mock plan
contains two encrypted PAY_PER_REQUEST tables and two policies scoped to their matching table.
They do not prove AWS permissions, billing, or DynamoDB behavior.

Use [the managed verification runbook](../../../docs/phase-5-managed-dynamodb.md) after a
fresh access/cost review and explicit deployment approval. The runner has separate modes:
`--plan-only` creates no resource, `--execute` is the only mode that can apply, and
`--cleanup-only` exists for recovery. `--execute` additionally requires
`PHASE5_MANAGED_DEPLOYMENT_APPROVED=yes`. It runs the existing service repositories against
the two AWS tables, verifies created/unchanged/conflicting replay and scoped reads, then
destroys only state-owned resources and checks the exact table names and policy ARNs are gone.
