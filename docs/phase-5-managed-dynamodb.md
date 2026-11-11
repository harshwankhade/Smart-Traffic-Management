# Phase 5 managed DynamoDB verification preparation

Status: **verified and torn down**. Step 8 ran on 2026-11-11 using the reviewed temporary
scope. The roadmap's separate local-demo Step 6 remains unstarted. See
`docs/evidence/phase-5-managed.md` for the actual managed run and cleanup evidence.

`infrastructure/terraform/phase5` contains exactly two DynamoDB PAY_PER_REQUEST tables:
`<run>-recommendations` for Signal Recommendation and `<run>-summaries` for Traffic
Analytics. Both use the approved `intersection_id` / `window_key` key schema, no secondary
index, AWS-owned encryption, and run-scoped tags. It creates two unattached IAM policies. Each
policy can only describe, get, put, and query the owner service's table. It creates no role
attachment, VPC, EKS, MSK, Lambda, alert, or recovery-event resource.

The verification runner creates a unique `stp5-<UTC timestamp>` name. It uses existing
`RecommendationRepository`, `SummaryRepository`, and the deterministic `recommend()` rule to
check real managed writes, strong reads, scoped query pagination, identical replay (`unchanged`),
and changed-content replay (`RecordConflict`). The test uses no Kafka or local DynamoDB endpoint;
Kafka integration remains the separately verified local Step 4 evidence. Test records stay only
in run-owned tables, which Terraform destroys in the runner's `finally` path.

The 2026-11-11 preflight passed with `smarttraffic-sdk`: STS identified the account root
principal, DynamoDB listed no existing tables, and account/table limits were 80,000/40,000 read
and write capacity units. The AWS-backed Terraform plan contained only the guard, two tables,
and two policies, with no change or delete action. Cost Explorer reported an estimated US$2.1674
month-to-date total through 2026-11-12, leaving about US$2.83 of the US$5 cap. AWS Pricing
returned US$0.71 per million standard on-demand write request units in Mumbai, effective
2026-11-01. The planned test uses roughly 14 small writes and a small number of reads, so its
incremental DynamoDB request cost is far below one cent; storage lasts only until teardown.
Current total spend can still change, and the preflight does not prove create/delete permission
until execution. Explicit approval to create the listed resources remains required.

After those gates and explicit approval, use the project-root commands below. First perform an
AWS-backed plan; it is read-only and records the exact proposed changes. Review that it contains
only two `aws_dynamodb_table` and two `aws_iam_policy` creates plus the guard.

```powershell
$env:AWS_PROFILE = 'your-reviewed-profile'
$env:AWS_REGION = 'ap-south-1'
.venv\Scripts\python scripts\run_phase5_managed.py --plan-only
```

For the separately approved temporary execution, set the extra guard value and run exactly one
command. Do not invoke `terraform apply` manually.

```powershell
$env:PHASE5_MANAGED_DEPLOYMENT_APPROVED = 'yes'
.venv\Scripts\python scripts\run_phase5_managed.py --execute
Remove-Item Env:PHASE5_MANAGED_DEPLOYMENT_APPROVED
```

The runner saves plan or managed evidence under `docs/evidence/`, retains its ignored local
Terraform variables/state until cleanup completes, and then invokes Terraform destroy against
that state. Cleanup succeeds only when the state is empty and AWS reports both exact run table
names and policy ARNs absent. If execution is interrupted, do not create a new run: use
`--cleanup-only` with the existing local run state after confirming it identifies the intended
run. Do not delete resources by name outside the runner.

Phase 7 remains reserved for distinct recovery-event storage and API work; this module does not
create or query recovery events.
