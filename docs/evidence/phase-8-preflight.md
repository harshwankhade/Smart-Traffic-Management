# Phase 8 Step 1 read-only AWS preflight

Date: 2026-11-12. Profile `smarttraffic-sdk`; region `ap-south-1`. No create, update, apply or delete command was run.

## Access and inventory

`aws sts get-caller-identity` returned account `520646131316` and principal `arn:aws:iam::520646131316:root`. Available zones are `ap-south-1a`, `ap-south-1b` and `ap-south-1c`.

Read-only list queries filtered to `stp*` or `smarttraffic*` names found no EKS clusters, MSK clusters, active EMR clusters, RDS instances, DynamoDB tables, S3 buckets, SQS queues or Lambda functions. This verifies no matching standing resources; it does not inventory unrelated account resources.

## Checked quotas

| Service | Relevant quota | Value |
|---|---|---:|
| EKS | Clusters / managed-node-group nodes | 100 / 450 |
| MSK | Brokers per account / cluster | 90 / 30 |
| EMR | Active clusters | 500 |
| RDS | DB instances | 20 |
| Lambda | Concurrent executions | 10 |

## Cost gate

`aws ce get-cost-and-usage` for 2026-11-01 through 2026-11-13 returned estimated unblended account usage of **US$6.4865880038**. Against the US$10.00 project cap and US$0.50 reserve, that leaves US$3.5134119962 below the cap and US$3.0134119962 below the US$9.50 predeployment gate. The account-wide service breakdown includes Kinesis, KMS and tax, so it is not a project-only bill and can lag posted charges.

Result: access and the sampled capacity checks pass, but a Phase 8 apply still requires a dated Mumbai calculator estimate and explicit deployment approval.
