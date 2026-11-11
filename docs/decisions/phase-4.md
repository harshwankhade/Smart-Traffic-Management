# Phase 4 execution decisions

Decision history begun 2026-11-10. Current Phase 4 status: **Completed** on 2026-11-11.
Entries below are chronological; later approved EMR decisions and live evidence supersede the
earlier managed-service assumptions and pre-deployment blockers.

User authorized Phase 4 implementation and deployment work. Existing Phase 1 rules remain the
baseline: Java 17, AWS Mumbai managed Flink, separate Kafka results, approved minute windows,
10-second watermark tolerance, 30-second idleness and bounded event-ID deduplication.
No Phase 5 work is authorized. The US$5 total cap is unchanged.

Use Flink 2.2.0 and Kafka connector 4.0.0-2.0, matching AWS's published managed-2.2
connector guidance. Maven 3.9.11 builds a shaded job, leaving Flink libraries provided by the
runtime. Jackson BOM 2.18.6 aligns all Jackson artifacts. IAM plugin 2.3.4 and managed runtime
property loader 1.2.0 are packaged; AWS execution remains unverified.

Implementation details: 24-hour processing-time dedup TTL from first insert; no TTL refresh for
retries. Count/log/drop conflicting direct Kafka IDs. Use arbitrary-precision count sums and
DECIMAL128 mean division. Millisecond event-time assignment preserves UTC window boundaries.
Use an at-least-once Kafka result sink with stable window keys rather than claim unproven
cross-system exactly-once delivery. Full contract/recovery behavior is in
[processing documentation](../phase-4-processing.md).

Local Flink runs in Docker infrastructure containers, not a ninth application service.
The Phase 3 broker gains a non-published internal listener; all original host endpoints and
persistent volumes remain. Flink checkpoints are shared persistent files. The real demo verifies
restoration of pending aggregates and deduplication state after cluster restart.

Terraform reuses existing Phase 2 network and Phase 3 Kafka/S3 outputs. It adds the managed
application, artifact object, result topic, role/policies, CloudWatch logs and tightly scoped
network rules. No second VPC, broker cluster, RDS, NAT gateway or EKS is introduced. Default
deployment and start gates remain false. Managed storage/snapshot operation is not inferred
from local Docker behavior or mock-provider success.

Cloud execution could not proceed: AWS CLI lists no profiles; Boto3 finds no credentials or
configured region in the current session. No credential values were read or printed. No live
account/quota tests, AWS-backed plan, apply, managed job status or managed output evidence
exists. A complete Mumbai lifecycle estimate and teardown review within US$5 is still required,
including the prerequisite roots, RDS safeguards, Kafka lifecycle, Flink orchestration/storage,
versioned objects, snapshots/logs, network/client costs and taxes. A 20-minute demo duration
does not establish the billable lifecycle. Do not raise the cap or silently substitute local proof.

Public suitability evidence checked 2026-11-10:

- [AWS Flink 2.2 and supported connectors](https://docs.aws.amazon.com/managed-flink/latest/java/flink-2-2.html)
- [Connector guidance](https://docs.aws.amazon.com/managed-flink/latest/java/how-flink-connectors.html)
- [Private VPC connectivity and managed state](https://docs.aws.amazon.com/managed-flink/latest/java/vpc.html)
- [VPC execution-role permissions](https://docs.aws.amazon.com/managed-flink/latest/java/vpc-permissions.html)
- [Managed snapshot recovery](https://docs.aws.amazon.com/managed-flink/latest/java/how-snapshots.html)
- [Pricing components](https://aws.amazon.com/managed-service-apache-flink/pricing/)

These are suitability references, not account entitlement, regional pricing or actual deployment proof.

## Authentication follow-up - 2026-11-10

The user completed browser login. Outside the filesystem/network sandbox, CLI identity and
read-only Mumbai MSK/Flink list calls succeeded; both application/cluster lists were empty.
The signed-in identity is root; use a scoped non-root identity before deployment.
MSK's account quota query reported 90 brokers/account and 30 brokers/cluster. Flink's applied
quota list was empty; its default quota query reported 64 KPUs and 100 applications. Defaults
are not proof of account-specific allocation, provisioning eligibility or available capacity.

The direct Boto3 login provider required an uninstalled CRT extra. Instead of changing project
dependencies, added local profile `smarttraffic-sdk` with a credential process delegating to
the existing `smarttraffic` CLI login. A Boto3 STS identity call then succeeded with provider
`custom-process`. No secret values were printed or added to project files. Use
`AWS_PROFILE=smarttraffic-sdk` and `AWS_REGION=ap-south-1` for project SDK/Terraform commands;
renew the browser session with `aws login --profile smarttraffic` when needed.

Authentication is now verified. Deployment remains unapplied: the complete US$5 lifecycle
estimate, remaining account/region checks and private data-plane verification access are still
outstanding. No resources were created by these read-only checks.

## Temporary managed test authorized - 2026-11-10

The user instructed: "leave the cost estimate, i want you to test the remaining phase 4 and
then tear down the resources after you are done." This explicitly waives the written estimate
gate and authorizes temporary Phase 4 provisioning and removal of run-created resources.
The existing US$5 total cap is not increased. Root access remains an administrator identity
for provisioning; the managed application uses its own scoped service role.

`phase4-live` composes the existing Phase 2/3/4 modules into an isolated, uniquely named test.
Phase 2's database instance is optional for this run only (default remains enabled), with a
state move preserving existing database addresses. No RDS instance, EC2 instance, EKS or NAT
gateway is planned. The real reviewed plan contains 45 resource creates and no replacements.
Networking, Kafka, S3, IAM, logs and the managed job remain Terraform-owned.

An explicitly enabled verification branch in the same managed application seeds acknowledged
synthetic Kafka readings and independently consumes actual results. It is off by default and
does not add a ninth service, public host or external private-network client. Temporary extra
Kafka topic permissions apply only with verification enabled. The test checks an initial window,
then pending-window/dedup recovery after a managed stop/snapshot/restart. Expected restored
window: three distinct speed readings 45, 25 and 50, mean 40; a repeated ID must not inflate it.

The runner attempts teardown in `finally`, empties only the run-owned versioned artifact bucket
after exact name/account checks, removes managed snapshots, destroys the recorded stack and
checks independent service inventories. Live results and cleanup evidence are recorded only
after actual execution, in `docs/evidence/phase-4-cloud.json`.

## User cancellation and verified teardown - 2026-11-10

The user interrupted the managed test while the MSK cluster was still `CREATING`, then
requested: "i want you to tear down all aws resources created". The runner and its exact
Terraform/provider process tree were stopped, preventing subsequent provisioning. The
already-created MSK cluster was imported into this run's Terraform state because its creation
had not completed before interruption. Cleanup then destroyed the stack and emptied the state.

Run `stp4-744bcf8057` is fully removed. Independent AWS API queries found no run-owned cluster,
configuration, application, bucket, VPC, security group, network interface, log group, database
instance/subnet group/parameter group, project role or project policy. The newly created Kafka
service-linked role was also removed after validating its exact creation timestamp/path;
AWS confirmed role deletion succeeded. Evidence: `docs/evidence/phase-4-cleanup.json`.

No managed Flink application was started or verified; Phase 4 remains In Progress. The ignored
run variables are reset to deployment/start disabled. No restart/redeployment is authorized by
this teardown request. Existing local Kafka/Flink data and unrelated AWS resources were not deleted.

## Second managed attempt blocked by AWS account verification - 2026-11-10

The user again authorized completing the remaining Phase 4 managed test and tearing down afterward.
Run `stp4-2b4decb230` used a newly reviewed 45-create plan with no RDS instance, EC2 instance, NAT
gateway, EKS, replacement or deletion. The private two-broker MSK cluster became `ACTIVE` after
approximately 29.4 minutes, and Terraform created `traffic.raw` and `traffic.results`.

AWS rejected the next `CreateApplication` call with `UnsupportedOperationException` and stated that
account `520646131316` needs additional verification by the AWS Account Verification team. Therefore
no managed Flink job started, no known Kafka output was observed, and no managed snapshot/restart
claim is made. This is an external account gate, not evidence of a job or IaC correctness failure.

The runner entered teardown automatically. Terraform state became empty, and independent inventory
checks found no run-owned MSK cluster/configuration, Flink application, S3 bucket, VPC, security
group, network interface, log group, database metadata, project IAM role or policy. The test-created
Kafka service-linked role was removed. Deployment and start flags are disabled. Phase 4 is **Blocked**
until AWS account verification is resolved; another billable deployment requires fresh user approval.

## Retry after reported account verification - 2026-11-10

The user reported completing account verification and authorized the remaining Phase 4 test. AWS
login was renewed, Terraform state was empty, and run `stp4-0ad61bb2ad` used a fresh reviewed plan.
Its two-broker MSK cluster became active after 26 minutes 55 seconds and both Kafka topics were
created. Nevertheless, managed Flink `CreateApplication` returned the same
`UnsupportedOperationException`; request ID `7d90cf1c-4058-475d-a065-4acc8831193e` states that the
account still needs additional AWS Account Verification team action. No application was created.

Automatic teardown succeeded. The independent audit again found no run-owned cloud resources and
removed the run-created Kafka service-linked role. Deployment flags are disabled. Before another
billable retry, AWS support must confirm that verification specifically enables Managed Service for
Apache Flink application creation in `ap-south-1`; a general account-verification completion is not
yet reflected by the service API.

## Approved platform change: Amazon EMR on EC2

The user approved Apache Flink on an **Amazon EMR on EC2 managed cluster** as the Phase 4 cloud
processor. This replaces Amazon Managed Service for Apache Flink, whose `CreateApplication` API
rejected both temporary attempts. The assignment's managed processing placement is retained as
approved by the user; the source PDFs and eight prescribed services remain unchanged. The former
managed-service Terraform and runner are historical; the runner now refuses new provisioning.

The platform change requires a matching job binary. AWS's EMR release history shows
`emr-7.14.0` bundling Flink `1.20.0-amzn-8` with Java 17. The existing local job uses Flink
2.2.0 and Kafka connector 4.0.0-2.0. The user approved a separate EMR build, which uses Flink
1.20.0 and Kafka connector 3.4.0-1.20 in `target-emr/`. Six Java tests pass for each build.
The job now tolerates the missing Managed Service properties file on EMR. A read-only
`aws emr list-release-labels --region ap-south-1` check returned `emr-7.14.0`.

Private MSK/S3 connectivity, EMR cluster/instance roles, S3 checkpoint and savepoint storage,
YARN submission, live result and restart verification, IaC and teardown are still required before
Phase 4 completion. No new AWS resources were created by this decision or the build. The US$5
total cap is unchanged; EMR/EC2 lifecycle cost and sizing remain an unresolved deployment gate.

Primary AWS references: [EMR Flink release history](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/Flink-release-history.html),
[EMR 7.14 release](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/emr-7140-release.html),
[Flink job submission on EMR](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/flink-jobs.html),
and [EMR Flink checkpoints](https://docs.aws.amazon.com/emr/latest/ReleaseGuide/flink-restart.html).

## Second EMR attempt permission diagnosis - 2026-11-11

Read-only EMR, CloudTrail and IAM queries identified the precise failure for cluster
`j-04400973T3BOB6RAIGP2`. The cluster terminated with `VALIDATION_ERROR`; during its launch,
four `RunInstances` events made through the EMR service role failed with
`Client.UnauthorizedOperation`. CloudTrail states that the role lacked `iam:PassRole` on the
custom EC2 role `stp4-97b99da46f-emr-ec2`.

The attached AWS-managed `AmazonEMRServicePolicy_v2` policy, default version `v6`, permits EC2
role passing only for `arn:aws:iam::*:role/EMR_EC2_DefaultRole`, conditioned on
`iam:PassedToService` matching `ec2.amazonaws.com*`. It therefore did not cover this project's
custom role. Successful VPC, subnet, route, security-group, network-interface and ingress calls,
together with the required EMR managed-policy tag in the Terraform configuration, do not support
a tag condition as the primary failure. Live tags are no longer queryable because teardown had
already removed the run resources.

The narrow correction for the next authorized implementation step is an explicit
`iam:PassRole` grant from the EMR service role to only the custom EC2 role ARN, with the EC2
passed-service condition. No correction was applied and no AWS resource was created in this
diagnostic step. Sanitized evidence is in
[`phase-4-emr-permission-diagnosis.json`](../evidence/phase-4-emr-permission-diagnosis.json).

## EMR IAM and teardown correction - 2026-11-11

The diagnosed correction is now implemented in Terraform. The EMR service role has one inline
`iam:PassRole` grant whose resource is the stack's exact custom EC2 role and whose
`iam:PassedToService` condition is exactly `ec2.amazonaws.com`. The AWS-managed EMR policy remains
attached; no wildcard role-passing permission was added.

The primary, core and service-access EMR security groups now use
`revoke_rules_on_delete = true`. This makes the AWS provider revoke rules added by EMR before it
deletes those security groups. The runner records only EMR security-group IDs obtained by walking
the current run's Terraform state; it does not discover or mutate unrelated groups. Plan-only
evidence is separate from managed-run evidence, and a plan/authentication failure resets the local
deployment guard to false.

Formatting, both module validations, Python compilation and all seven Phase 2-4 mocked Terraform
tests passed. The authenticated reviewed plan contains 63 creates, zero changes and zero destroys:
one private EMR 7.14/Flink cluster, two-broker MSK, two topics, private S3/checkpoint storage and
their guarded network/IAM dependencies. It contains no RDS instance, NAT gateway, EKS cluster,
standalone EC2 resource or former managed-Flink application. Terraform state remains empty and
`deployment_approved` is false. No apply ran and no AWS resource was created. Evidence:
[`phase-4-step-2.json`](../evidence/phase-4-step-2.json).

## Managed EMR verification and removal - 2026-11-11

The user authorized remaining step 5 and a same-session teardown. Run `stp4-91dd0a43a8`
started from a reviewed 63-create plan. On the user's temporary pause, the local apply stopped
while MSK continued to `ACTIVE` in AWS. After the user authorized continuation, the exact
run-owned MSK ARN was imported into its partial Terraform state. The fresh continuation plan
contained seven creates, one JAR object update and no deletions/replacements.

The private EMR 7.14/Flink 1.20 cluster launched with the scoped service/EC2 roles, IAM/TLS
connectivity to two-broker MSK and S3 checkpoint storage. Both YARN verification steps completed.
Stage 1 consumed `traffic.raw` and observed a `traffic.results` medium-congestion window with
two readings, count sum 5, mean speed 20 and mean occupancy 0.6. A completed checkpoint receipt
identified checkpoint 1 after the pending inputs passed the operator. The job was stopped and
stage 2 restored that exact S3 checkpoint. It observed a low-congestion window with three
distinct speed readings averaging 40; the retried ID did not inflate the count. The runner
validated both actual Kafka-derived records against `contracts/v1/result.schema.json` and
independent expected fields. These are bounded demonstration cases, not an exactly-once or
24-hour TTL soak guarantee.

The EMR cluster terminated, the exact state-owned versioned bucket was emptied, Terraform
destroy left empty state, and the deployment guard returned to false. A separate audit found
no run-owned EMR/MSK/S3/network/log/RDS/IAM resources and removed the Kafka service-linked role
created during this run. Evidence: [managed result](../evidence/phase-4-cloud.json),
[cleanup audit](../evidence/phase-4-cleanup.json). The user waived a written cost estimate;
actual charges and compliance with the unchanged US$5 cap were not measured. The full cloud
application deployment remains future work; Phase 5 has not started.
