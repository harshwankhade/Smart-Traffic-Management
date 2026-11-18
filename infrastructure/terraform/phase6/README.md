# Phase 6 guarded alert infrastructure

This independent Terraform root defines one SQS Standard alert queue and DLQ, one on-demand encrypted `traffic_alerts` DynamoDB table, one Python 3.14 Alert Service Lambda, its SQS event-source mapping, a seven-day CloudWatch log group, and narrowly scoped IAM. The Lambda execution role can receive/delete messages from the source queue, get/put items in its own table, and write its own log streams. Separate **unattached** `sqs:SendMessage` policies are prepared for Signal Recommendation and Incident Manager; workload identity attachment belongs to the later integrated deployment. No public endpoint, EKS, MSK, RDS, or other application service is created here.

The source queue has 60-second visibility, redrives to the DLQ after five receives, and invokes Lambda in batches of five with `ReportBatchItemFailures` and maximum concurrency two. Lambda has a 10-second timeout and 128 MiB memory. The function code ZIP is built locally at `.data/phase6/alert-service.zip` and is ignored by Git. Build it on Python 3.14 from the pinned local environment:

```powershell
.venv\Scripts\python scripts\build_phase6_lambda.py build
.venv\Scripts\python scripts\build_phase6_lambda.py check
terraform -chdir=infrastructure/terraform/phase6 init -backend=false -input=false
terraform -chdir=infrastructure/terraform/phase6 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase6 validate
terraform -chdir=infrastructure/terraform/phase6 test
```

The ZIP builder checks versions against `requirements-lock.txt`, includes application code and pure-Python Boto3 dependencies, and verifies import/smoke behavior from the extracted artifact. The lock file pins AWS provider 6.45.0. The mock tests run **plan only** and verify the default deployment guard, queue/DLQ settings, table, Lambda mapping and IAM scope. They make no AWS calls and cannot prove regional permissions, actual invocation, billing, or correct cloud teardown.

## Later temporary deployment and teardown

**Do not run these commands in Step 4.** Before any billable deployment, obtain a reviewed full-lifecycle cost estimate within the US$10 total ceiling and US$0.50 reserve, check account access/quotas, and get explicit authorization for the exact temporary run. Use a unique lowercase run ID and the approved AWS profile. Keep the same Terraform state and `project_name` for teardown.

```powershell
$env:AWS_PROFILE = 'APPROVED_PROFILE'
$env:AWS_REGION = 'ap-south-1'
terraform -chdir=infrastructure/terraform/phase6 init -input=false
terraform -chdir=infrastructure/terraform/phase6 plan -var 'deployment_approved=true' -var 'project_name=stp6-UNIQUE-RUN' -out=phase6-approved.tfplan
terraform -chdir=infrastructure/terraform/phase6 apply phase6-approved.tfplan
# Run the separately authorized SQS/Lambda/DynamoDB acceptance checks and save evidence.
terraform -chdir=infrastructure/terraform/phase6 destroy -var 'deployment_approved=true' -var 'project_name=stp6-UNIQUE-RUN'
terraform -chdir=infrastructure/terraform/phase6 state list
```

The reviewed plan must have only this root's run-owned resources and **no deletes** before apply. After destroy, verify empty Terraform state and independently check the exact run-owned queue/DLQ, table, function, log group, IAM role/policies and mapping are absent. The plan file and state may contain resource identifiers; keep them local. SQS messages, DLQ contents, Lambda logs and DynamoDB records are removed with these run-owned resources. A cloud test should send one congestion and one incident request directly to the queue until Phase 8 attaches the producer identities and integrates the full workloads.
