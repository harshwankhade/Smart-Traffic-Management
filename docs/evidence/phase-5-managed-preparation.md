# Phase 5 managed DynamoDB preparation evidence — 2026-11-11

The guarded Terraform module was formatted, initialized with the pinned HashiCorp AWS provider
6.45.0, validated, and mock-tested locally. `terraform validate` passed. `terraform test`
passed both checks: the default deployment guard rejects a real plan, and the mock-enabled plan
contains exactly the approved two on-demand encrypted tables and two service-owned policies.
`scripts/run_phase5_managed.py` and `tests/test_phase5_managed.py` compiled. The opt-in managed
test was intentionally skipped in the ordinary environment.

The configured `smarttraffic-sdk` profile then passed a read-only AWS preflight. STS identified
the account root principal; DynamoDB listed no tables and reported 80,000 account and 40,000
table read/write capacity-unit limits. Cost Explorer returned an estimated US$2.1674009494
month-to-date total through 2026-11-12, leaving about US$2.83 of the US$5 cap. AWS Pricing
reported US$0.71 per million standard on-demand write request units in Mumbai, effective
2026-11-01. The short test's approximately 14 small writes and few reads are far below one cent.

`scripts/run_phase5_managed.py --plan-only` completed against AWS. Its reviewed plan has five
creates only: `terraform_data.deployment_guard`, two uniquely named DynamoDB tables, and two
unattached owner policies. No AWS-backed apply, DynamoDB write/read, IAM policy creation, or
teardown ran. Exact create/delete permission remains unproven until an approved execution. The
runner requires both `--execute` and `PHASE5_MANAGED_DEPLOYMENT_APPROVED=yes` before an apply,
then records state-scoped teardown and independent absence checks for only its two table names
and policy ARNs.

This preparation evidence was superseded by the successful temporary Step 8 execution and
cleanup recorded in [phase-5-managed.md](phase-5-managed.md).
