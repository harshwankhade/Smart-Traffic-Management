# Phase 6 temporary cloud acceptance runbook

Status: **preparation only**. This runbook does not authorize deployment. The Phase 6 runner creates only the run-scoped SQS source queue and DLQ, DynamoDB alert table, Lambda and SQS mapping, CloudWatch log group, Lambda role/runtime policy, two unattached producer send policies, and the Terraform guard. It does not deploy producer services, Kafka, RDS, EKS, or a public endpoint.

## Read-only preparation

Use an authenticated, reviewed AWS profile in `ap-south-1`. Verify current month-to-date account charges and the remaining US$5 total budget, account quotas, and an AWS-backed plan before seeking deployment approval. The default `smarttraffic-sdk` profile may need `aws login --profile smarttraffic` first.

```powershell
$env:AWS_PROFILE = 'smarttraffic-sdk'
$env:AWS_REGION = 'ap-south-1'
.venv\Scripts\python scripts\phase6_cloud.py --plan-only
```

The runner checks AWS Cost Explorer's estimated month-to-date unblended spend, builds and checks the Lambda ZIP, creates a unique `stp6-<UTC timestamp>` run name, and writes a plan summary to `docs/evidence/phase-6-cloud-plan.json`. It rejects a plan unless it contains exactly eleven **create** actions: one guard, two queues, one table, one log group, one IAM role, one inline role policy, two unattached send policies, one Lambda function and one mapping. It does not apply resources. The execute mode checks spend again and refuses deployment if the estimate is unavailable or at least US$7.50, reserving US$0.50 below the user-approved US$8 cap. Cost Explorer can lag and this guard does not guarantee final billing.

## Separately approved temporary execution

After reviewing the exact plan and full-lifecycle cost, obtain explicit approval for this run. Then set the additional flag and execute the saved plan:

```powershell
$env:PHASE6_CLOUD_DEPLOYMENT_APPROVED = 'yes'
.venv\Scripts\python scripts\phase6_cloud.py --execute
Remove-Item Env:PHASE6_CLOUD_DEPLOYMENT_APPROVED
```

The runner sends one congestion and one incident request directly through SQS, checks DynamoDB outcomes and Lambda logs, repeats a request to verify idempotence, and sends a valid same-ID conflict to exercise five receives and DLQ redrive. The DLQ test may take up to eight minutes with the approved 60-second visibility timeout. It recovers the run-owned test case by removing the original test record and replaying the exact DLQ body; the intended new outcome is verified before the DLQ message is deleted. This test does not claim that arbitrary malformed production messages can be repaired by replaying unchanged bytes.

The `finally` path destroys only the Terraform state-owned resources and audits their exact absence, including the mapping and log group. Evidence goes to `docs/evidence/phase-6-cloud.json`. If interrupted, preserve the local `.data/phase6-cloud` run variables and Terraform state; **do not start a new run**. After confirming the run name and state, use:

```powershell
.venv\Scripts\python scripts\phase6_cloud.py --cleanup-only
```

The runner requires `PHASE6_CLOUD_DEPLOYMENT_APPROVED=yes` for `--execute`. `--cleanup-only` is recovery for an existing run, not authorization for a new deployment. The eventual Phase 8 workload deployment must attach the producer IAM policies and test the complete producer-to-Lambda path. Phase 6 cloud acceptance proves the queue-triggered Alert Service path directly, alongside the existing local producer tests.

If a full approved run has already verified DLQ redrive and same-body recovery but its log inspection failed, a **separately approved new plan** may use `--execute --logs-only`. That mode repeats the two alert paths, duplicate and conflict logging with paginated CloudWatch reads, then tears down and audits the new run. It does not repeat the several-minute DLQ recovery test; final acceptance must cite the earlier DLQ evidence and the later logging evidence together.
