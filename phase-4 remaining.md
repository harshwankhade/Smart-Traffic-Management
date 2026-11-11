# Phase 4 remaining work — one step per prompt

**Current state (11 November 2026):** Phase 4 is **Completed**. Local Flink and the temporary
EMR 7.14/Flink 1.20 managed test passed. Both EMR verification steps completed; checkpoint
recovery and expected Kafka results were observed. Terraform state is empty, deployment is
disabled, and the independent audit found no run-owned AWS resources. The prior failed attempts
and their corrections are recorded below. Actual billed cost was not checked. Phase 5 is Not Started.

Work through these steps in order. Each prompt authorizes **only its named step**. After each step, report what changed, the checks actually run, and the next blocker; then stop. A failed check stays in that step until resolved. Do not start Phase 5.

## 1. Find the exact EMR permission failure - completed 11 November 2026

Inspect the second failed cluster's EMR status, relevant CloudTrail denial events, the EMR service-role policy and resource tags. Identify the specific missing EC2 permission or tag condition. Use read-only AWS calls; record evidence without exposing credentials. If AWS does not expose a precise denial, document the remaining uncertainty and the narrowest supported correction.

**Done when:** The likely cause is supported by AWS evidence or explicitly marked unresolved. No resources are created.

**Result:** CloudTrail confirmed that `RunInstances` failed because the custom EMR service role
did not have `iam:PassRole` for the custom EC2 instance role. The attached managed policy covers
only `EMR_EC2_DefaultRole`. No resource was created and no correction was applied; see
`docs/evidence/phase-4-emr-permission-diagnosis.json`.

**Prompt:** `Do Phase 4 remaining step 1 only: diagnose the EMR service-role EC2 permission failure with read-only evidence, then stop.`

## 2. Correct EMR infrastructure and cleanup - completed 11 November 2026

Make the smallest Terraform/IAM/tag correction justified by step 1. Keep the approved private EMR 7.14 cluster, two-broker MSK, S3 checkpoint path and deployment guard. Make teardown handle EMR-added security-group rules that blocked the second destroy; restrict cleanup to IDs from this run's Terraform state. Update the EMR Terraform runbook, which still describes the superseded managed-service design.

**Done when:** Terraform formatting, validation and mocked tests pass; a reviewed plan has no unexpected resources or deletions. No AWS apply is run.

**Result:** Added the exact custom-role `iam:PassRole` grant and state-owned EMR security-group
rule revocation. Updated the EMR runbooks and hardened plan/cleanup evidence handling. Formatting,
validation and seven mocked tests passed. The authenticated plan has 63 creates, no changes or
deletions, and no forbidden resource types. State is empty, deployment is disabled and no apply ran.
See `docs/evidence/phase-4-step-2.json`.

**Prompt:** `Do Phase 4 remaining step 2 only: fix the evidenced EMR IAM/IaC issue and run-owned teardown path; validate locally, then stop.`

## 3. Check the Flink job and verification runner locally - completed 11 November 2026

Rebuild both Flink profiles and run their tests. Review the EMR submit command, S3 checkpoint discovery, restore command, known-input/known-output checks, timeouts, failure handling and evidence writing. Fix demonstrated issues before another billable run. Preserve the local Flink 2.2 path and the eight-service architecture.

**Done when:** The Java tests, runner checks and relevant local Phase 4 demo pass; the cloud run can fail safely at each stage. No AWS apply is run.

**Result:** Both Flink profiles rebuilt with seven tests each. The Python suite passed 36 tests,
including five new offline runner checks. The real local Kafka/Flink demo passed after its consumer
was corrected to start at Kafka's current low watermark. The runner now waits for a completed
checkpoint that includes both pending readings, restores that checkpoint ID, validates full
known-output records, recovers exact IDs from partial Terraform state and still attempts destroy
after an EMR or S3 cleanup error. The demo job was canceled. No AWS apply ran. See
`docs/evidence/phase-4-step-3.json`.

**Prompt:** `Do Phase 4 remaining step 3 only: verify and harden the Flink job and EMR test runner locally, then stop.`

## 4. Complete the deployment preflight - cloud/teardown checks completed 11 November 2026

Use read-only AWS checks to confirm the intended account/region, EMR and EC2 quotas, instance availability, IAM readiness and no leftover run resources. Review current spend and the full expected MSK + EMR + storage lifecycle against the project's US$5 ceiling. Prepare one fresh run ID and a concrete plan with resource counts, time limits and teardown checks. Do not deploy in this step.

**Done when:** The plan is reviewable and the cost/access decision is explicit. If the ceiling cannot be met, record that blocker and stop before provisioning.

**Result:** Read-only account, Mumbai quota, instance offering, IAM and residual-resource checks
were recorded in `docs/evidence/phase-4-step-4.md`. Fresh run `stp4-91dd0a43a8` has a reviewed
63-create, zero-change, zero-delete plan, empty Terraform state and a disabled deployment guard.
Two EMR nodes would consume all eight available standard EC2 vCPUs. The earlier waiver of a
written estimate remains recorded, but current spend and the US$5 ceiling were not verified in
this narrowed cloud/teardown prompt. No apply ran; actual instance capacity and new-role IAM
behavior remain unproven.

**Prompt:** `Do Phase 4 remaining step 4 only: perform the read-only cloud, cost and teardown preflight; do not deploy, then stop.`

## 5. Run the managed test and tear down in the same session - completed 11 November 2026

Only after steps 1–4 pass, run the reviewed temporary Terraform deployment. On EMR, verify a known input produces the expected `traffic.results` record, then restore from a retained S3 checkpoint and verify the pending-window and duplicate behavior. Capture the EMR job/step status, actual Kafka-derived results and checkpoint evidence. Whether the test passes or fails, terminate the cluster, empty only the run-owned versioned bucket, destroy the Terraform stack and audit AWS before ending this step. Do not leave billable resources waiting for another prompt.

**Done when:** Managed evidence or a precise failure is recorded, Terraform state is empty, deployment is disabled and an independent audit finds no run-owned resources. If cleanup fails, focus on cleanup before ending the step.

**Result:** Run `stp4-91dd0a43a8` was interrupted at the user's request while MSK was
provisioning, then resumed after the user authorized continuation. The exact active MSK cluster
was imported into the partial Terraform state. A reviewed continuation plan had seven creates,
one JAR object update, and no deletes or replacements. EMR 7.14 steps 1 and 2 both completed.
Stage 1 produced the expected medium-congestion result from two readings; restoration from S3
checkpoint 1 produced the expected three-reading, low-congestion pending window with duplicate
suppression. The EMR cluster terminated, the run-owned versioned bucket was emptied, Terraform
destroy left empty state, and the deployment guard returned to false. The independent AWS audit
found no run-owned resources and removed the Kafka service-linked role created during the first
apply. See `docs/evidence/phase-4-cloud.json` and `docs/evidence/phase-4-cleanup.json`.
Current billed cost was not verified.

**Prompt:** `Do Phase 4 remaining step 5 only: run the approved EMR known-output and checkpoint-recovery test, complete teardown and audit it in this session, then stop.`

## 6. Close Phase 4 documentation - completed 11 November 2026

Reconcile the README, architecture, decision record, Terraform runbook and Phase 4 progress report with the actual results of step 5. Record commands, observed outputs, limitations and cleanup evidence. Mark Phase 4 **Completed** only if the managed job consumed `traffic.raw`, wrote correct results to `traffic.results`, checkpoint/restart behavior matched the approved rules, IaC was reproducible, and teardown was verified. Otherwise keep **In Progress** or **Blocked** with the exact unmet criterion.

**Done when:** Documentation and roadmap status match evidence. Phase 5 remains untouched.

**Result:** Reconciled README, architecture, Phase 4 decision record, processing contract,
both EMR Terraform runbooks, the 200-300-word Phase 4 report and roadmap with the managed
result and independent cleanup audit. Phase 4 is marked Completed for its scoped acceptance
criteria. The temporary stack is gone; the full cloud system and cost verification remain
outside this phase. Phase 5 remains Not Started.

**Prompt:** `Do Phase 4 remaining step 6 only: reconcile evidence and documentation, set the justified Phase 4 status, then stop.`
