# Phase 4 remaining step 4: read-only cloud and teardown preflight

Checked 2026-11-11 in `ap-south-1` using `smarttraffic-sdk`. AWS STS returned account
`520646131316` with a root caller. No credential value was read or recorded. This preflight used
AWS `get`, `list`, `describe`, Terraform `plan`/`show`, and local tests. It ran no `apply`.

## Access and capacity

| Check | Observed result | Limit |
|---|---|---|
| EMR release | `emr-7.14.0` listed in Mumbai | Listing does not reserve capacity. |
| EMR quotas | 500 active clusters; 2,000 active instances per instance group | One planned cluster with one primary and one core fits these numbers. |
| EC2 quota | 8 standard on-demand vCPUs; no pending/running instances observed | Two `m5.xlarge` nodes need 4 vCPUs each, exhausting this quota. Any concurrent standard instance would block the plan. |
| Instance offering | `m5.xlarge` listed in `ap-south-1a`, `1b`, and `1c`; both planned subnet zones `1a` and `1b` available | Offering is not a capacity guarantee at launch. The EMR instance groups use the first subnet (`1a`). |
| MSK quotas | 90 brokers/account; 30 brokers/cluster | Two `kafka.t3.small` brokers fit; the previous run reached `ACTIVE`, but future provisioning is not guaranteed. |
| IAM | `AmazonEMRServicePolicy_v2` attachable, default version `v6`; Terraform plans an exact custom-role `iam:PassRole` grant before EMR creation | Custom roles do not exist until apply. The caller is root, not the preferred scoped deployment identity. IAM/SCP and service behavior are not proven by a plan. |
| MSK service-linked role | `AWSServiceRoleForKafka` absent | A later run may create it. The runner now records whether it preexisted, so the audit can remove it only if this run created it. |

Read-only inventories returned no active EMR cluster, MSK cluster/configuration, run-prefixed S3
bucket, project VPC/security group, run-prefixed ENI or log group, run-prefixed IAM role/policy,
or run-prefixed RDS instance/subnet/parameter group. Terraform state is empty.

## Prepared run and reviewed plan

Run ID: `stp4-91dd0a43a8`. The ignored run variables retain this name with
`deployment_approved = false`. `--reuse-reviewed-run` now requires matching plan evidence and
the disabled guard; if separately authorized later, it makes a fresh plan before applying.
The full address/action summary is in [phase-4-plan.json](phase-4-plan.json), and the saved binary
plan is under ignored `.data/phase4-cloud/`.

The reviewed plan has **63 creates, 0 updates, 0 deletes**: one private VPC, two isolated subnets,
six security groups and 27 explicit rules, an S3 gateway endpoint, a two-broker MSK cluster and
configuration, two Kafka topics, one private/versioned/encrypted S3 bucket and EMR artifact, one
EMR 7.14/Flink cluster with two `m5.xlarge` nodes, and IAM roles/policies/profile. Three of the
63 are Terraform guard resources. There is no RDS instance, NAT gateway, EKS cluster, standalone
EC2 instance resource or former managed-Flink application. EMR will launch its two underlying
EC2 instances if a later apply succeeds.

## Time limits and teardown for a later authorized run

The runner's current limits are: Terraform apply **70 minutes**; EMR readiness **30 minutes**;
each EMR step **20 minutes**; each result marker **15 minutes**; completed checkpoint receipt
**3 minutes**; EMR termination wait **30 minutes**; Terraform destroy **70 minutes**. EMR has a
**60-minute idle termination** setting. These are individual timeouts, not a total wall-clock or
billing cap. An error enters cleanup in the same runner session; an interrupted process requires
the original run variables and state for `--cleanup-only`.

Teardown must terminate the cluster ID from this run's state, wait for termination, empty versions
and delete markers only in the state-owned bucket after checking its owner/name, destroy Terraform
state resources, and verify an empty state. Then run `scripts/audit_phase4_cleanup.py
--remove-new-service-role` in the same session. The audit checks active EMR/MSK, bucket, VPC,
security groups, ENIs, logs, RDS metadata and IAM; it removes the MSK service-linked role only
when the recorded pre-run check says it was absent. If AWS created a cluster but Terraform never
recorded its ID, stop and reconcile that exact run before claiming cleanup. Do not rely on the
one-hour EMR idle setting to stop MSK charges.

The user previously waived a written cost estimate for temporary testing, while retaining a
US$5 total cap. This narrowed prompt did not request a spend estimate. Current spend and a full
MSK + EMR/EC2/EBS + S3 lifecycle total were **not** measured, so this preflight does not certify
the cap. [AWS EMR pricing](https://aws.amazon.com/emr/pricing/) adds EC2 and EBS charges to EMR;
[AWS MSK pricing](https://aws.amazon.com/msk/pricing/) adds broker and storage charges. The AWS
Cost Explorer API was not called; [AWS prices each API request at US$0.01](https://aws.amazon.com/aws-cost-management/aws-cost-explorer/pricing/).

Decision: the requested technical and teardown checks are complete, with zero EC2 quota
headroom and unverified capacity/IAM behavior. No deployment was authorized by this step, and no
claim of US$5 affordability is made. Phase 4 remains **In Progress**.
