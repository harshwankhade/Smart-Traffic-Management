# Temporary Phase 4 EMR managed verification

This root composes the existing private network, two-broker MSK/S3 module and current EMR 7.14
Flink module for a separately authorized temporary cloud test. It creates no RDS database
instance, public client, EKS cluster or NAT gateway. Private IAM/TLS Kafka connectivity is
exercised from the EMR job itself.

The user waived the written cost-estimate gate for this run and explicitly requested teardown.
The current US$10 total cap and US$0.50 reserve apply to any future run. `deployment_approved` defaults false; the runner writes
run-specific approved variables under ignored `.data/phase4-cloud/` only after authorization.

```powershell
terraform -chdir=infrastructure/terraform/phase4-live init -backend=false
.venv\Scripts\python scripts\run_phase4_cloud.py --plan-only
.venv\Scripts\python scripts\run_phase4_cloud.py --reuse-reviewed-run
```

The plan-only path creates no resources and writes separate plan evidence. A separately
authorized `--reuse-reviewed-run` requires the same run ID in the disabled variables and plan
evidence, and generates a fresh reviewed plan before any apply. The runner rejects RDS,
NAT, EKS, the former managed-Flink resource and any deployment-plan deletion/replacement. During
an authorized run, it submits the known-input verifier to EMR, reads actual results and tests
checkpoint restoration. Its `finally` cleanup resolves the cluster, bucket and EMR security groups
from this run's Terraform state. Terraform's three EMR security groups revoke EMR-added rules before
deletion; the runner does not discover or mutate unrelated security groups.

On interruption/failure, inspect the evidence and run `scripts/run_phase4_cloud.py --cleanup-only`
with the original ignored run variables and state retained. Never discard Terraform state before
confirmed cleanup. Cleanup may act only on IDs from that state; name-prefix queries after destroy
are read-only residual audits.

If an interrupted apply created an AWS cluster before Terraform recorded it, first verify its
exact run name and ARN with read-only AWS calls, import that exact resource into this run's state,
then generate and review a fresh plan. The runner's ordinary invocation resumes when the ignored
run variables already have `deployment_approved = true`; it replans before applying. An interrupted
run may need a separate service-linked-role baseline check because that role can be created before
the resume. Do not leave a provisioning process running unattended or discard partial state.

After destroy, run the independent audit in the same session:

```powershell
.venv\Scripts\python scripts\audit_phase4_cleanup.py --remove-new-service-role
```

The runner records whether `AWSServiceRoleForKafka` existed before apply. The audit removes it
only if this run created it, no run-owned MSK cluster remains, and its service-linked path matches.
It also checks active EMR, MSK, S3, VPC, network interfaces, logs, RDS metadata and IAM residue.

The normal Phase 2 database defaults remain available outside this temporary root. Phase 3's S3
gateway policy permits artifact/checkpoint access as well as normalized archive access.

## Observed temporary run (11 November 2026)

Run `stp4-91dd0a43a8` began with 63 planned creates. The apply was interrupted at the user's
request after MSK creation began; AWS completed MSK provisioning independently. Its exact ARN
was imported into the partial Terraform state. The continuation plan had seven creates, one
existing JAR object update, and no deletions/replacements. The resumed runner completed both
EMR 7.14 YARN steps and validated actual records consumed from `traffic.results`:

- Stage 1: two readings in 10:00-10:01 UTC, count sum 5, speed 20, occupancy 0.6, congestion `medium`.
- Stage 2: restored completed S3 checkpoint 1; three distinct readings in 10:01-10:02 UTC,
  speed 40, congestion `low`. Retried event IDs did not increase the reading count.

Commands used were `terraform import` for the exact MSK ARN, a fresh `terraform plan`,
`.venv\Scripts\python scripts\run_phase4_cloud.py`, and
`.venv\Scripts\python scripts\audit_phase4_cleanup.py --remove-new-service-role`.
The EMR cluster terminated; the state-owned versioned bucket was emptied; Terraform state is
empty and `.data/phase4-cloud/run.tfvars.json` again has `deployment_approved = false`.
The independent audit found no run-owned resources. See
[`phase-4-cloud.json`](../../../docs/evidence/phase-4-cloud.json) and
[`phase-4-cleanup.json`](../../../docs/evidence/phase-4-cleanup.json). The written estimate was
waived; current billed cost and the US$5 ceiling were not verified. No stack is left deployed.
