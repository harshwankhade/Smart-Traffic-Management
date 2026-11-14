# Phase 5 — steps to execute one prompt at a time

Status: Phase 5 is **Completed** for its approved scope. Steps 1–9 were authorized and completed on 2026-11-11; evidence and limitations are recorded in `docs/progress/phase-5.md`. This file breaks down Phase 5 of `ROADMAP.md` and does not authorize cloud provisioning.

Execute the steps in order, only when prompted. Each prompt authorizes **only its named step**. Read `AGENTS.md`, the authoritative root documents, approved decisions and relevant existing code before acting. Preserve prior behavior. After each step, record changes, actual checks, limitations and the next step, then stop. If a prerequisite fails, resolve it within that step before continuing. Do not start Phase 6.

Approved baseline: Signal Recommendation and Traffic Analytics remain two independent Python/FastAPI services; consume `traffic.results`; use DynamoDB for derived records. High congestion recommends a **simulated +10-second green adjustment**; other conditions recommend no adjustment. Use stable window keys and deterministic persistence. No physical signal control, queue emission, serverless alerts, final ZooKeeper recovery metrics or dashboards belong in Phase 5.

## 1. Review prerequisites and settle Phase 5 interfaces

Inspect the Phase 4 result schema/evidence, both service scaffolds, configuration and existing tests. Document the proposed recommendation/summary records, service ownership, DynamoDB keys/indexes, query routes, pagination/time boundaries, consumer groups, retry/offset behavior and conflicting replay policy. Reserve a documented extension for Phase 7 recovery events without implementing it. Identify material choices requiring approval; distinguish these from the already approved stack and rules. Present a concrete plan and likely files before dependent implementation.

**Done when:** Phase 5 decisions and acceptance checks are documented; any required material interface/design approvals are resolved before implementation. No cloud resources are created.

**Prompt:** `Do Phase 5 step 1 from "phase-5 steps.md" only: review prerequisites and prepare the Phase 5 interface, storage and delivery decisions for approval. Then stop.`

## 2. Define contracts and implement recommendation rules

Following approved step-1 decisions, add versioned recommendation/summary contracts and examples without breaking existing v1 contracts. Implement deterministic recommendation calculation with source inputs and rationale. Validate incoming results and deterministic identities. Test high, medium, low and unknown congestion, missing measurements, malformed records and repeated inputs. Keep Kafka and storage integration for subsequent steps.

**Done when:** Contract examples and focused rule tests pass; recommendations are explainable and simulation-only.

**Prompt:** `Do Phase 5 step 2 from "phase-5 steps.md" only: implement approved contracts and deterministic simulated recommendation rules with focused tests. Then stop.`

## 3. Implement DynamoDB persistence and local verification

Implement service-owned repositories for recommendations and window summaries using the approved keys and access patterns. Add environment configuration and the approved local DynamoDB-compatible test setup. Verify real local writes/reads, intersection/time queries, pagination, restart persistence and duplicate/conflicting replay handling. Reserve future alert ownership without implementing alerts. Keep dependency changes minimal and pinned.

**Done when:** Both repositories persist/query actual local records; replay preserves one logical record and conflicts follow the approved policy. Local results are explicitly distinguished from managed AWS proof.

**Prompt:** `Do Phase 5 step 3 from "phase-5 steps.md" only: implement service-owned DynamoDB persistence and verify it against the approved local setup. Then stop.`

## 4. Connect both services to Kafka results

Add independent consumers of `traffic.results` within the two existing services. Signal Recommendation validates results, calculates recommendations and persists them; Traffic Analytics persists validated summaries without repeating Flink aggregation. Implement the approved consumer lifecycle, retry, offset acknowledgement, invalid-record handling and shutdown behavior. Acknowledge successful processing only after durable persistence as agreed in step 1. Preserve liveness compatibility and document dependency readiness.

**Done when:** Real local Kafka results reach both stores; replay, process restart and storage outages demonstrate the agreed recovery behavior without duplicate logical state. Malformed records follow the documented policy.

**Prompt:** `Do Phase 5 step 4 from "phase-5 steps.md" only: integrate both Kafka result consumers and test persistence, replay, restart and outage behavior. Then stop.`

## 5. Expose and test recommendation and analytics APIs

Implement the approved REST routes for recommendations and persisted traffic summaries. Support the agreed intersection/time filters, pagination, validation, missing-record behavior and dependency errors. Test cross-intersection isolation, time boundaries, empty results and unavailable storage. Document configuration, requests, responses and the reserved Phase 7 extension.

**Done when:** Both services return persisted data through actual HTTP; scoped query and error checks pass; API documentation matches behavior.

**Prompt:** `Do Phase 5 step 5 from "phase-5 steps.md" only: implement and verify the approved recommendation and analytics REST APIs. Then stop.`

## 6. Add a reproducible local Phase 5 demo

Create a repeatable demo that sends known schema-valid results to actual Kafka, waits for both consumers and queries the APIs against independently calculated expectations. Include repeated results and recovery checks; verify persisted data survives service restart. Use unique test IDs and stop only owned processes. Run relevant existing regression checks and record commands, results and limitations.

**Done when:** The local Kafka-to-NoSQL-to-HTTP workflow is reproducible, checks both services and demonstrates idempotent reprocessing. This does not satisfy the managed-NoSQL acceptance criterion by itself.

**Prompt:** `Do Phase 5 step 6 from "phase-5 steps.md" only: build and run the reproducible local integration demo and relevant regression checks. Then stop.`

## 7. Prepare managed DynamoDB IaC and cloud verification

Add guarded Terraform for the approved Phase 5 tables/indexes and least-privilege access policies, keeping service ownership separate. Run formatting, validation and mocked plan tests. Prepare a narrowly scoped managed test and teardown runbook using the actual service code, with replay/read-back assertions and evidence output. Review lifecycle costs against the current US$10 total cap and US$0.50 reserve, authentication and cleanup boundaries. Do not recreate EMR/MSK or deploy EKS for this DynamoDB-specific proof. Any deviation requires approval.

**Done when:** IaC checks pass and the exact managed test, planned resources, cost constraints and teardown are reviewable. No apply runs. Record any unresolved deployment gate.

**Prompt:** `Do Phase 5 step 7 from "phase-5 steps.md" only: prepare and validate guarded DynamoDB Terraform and a concrete managed verification/teardown plan. Do not provision resources. Then stop.`

## 8. Verify actual managed DynamoDB and tear down

After step 7 is reviewable and its deployment gates are satisfied, provision only its approved temporary resources through Terraform. Use both services' real processing/persistence paths to write/read known records in AWS DynamoDB, query them through the APIs and verify repeat delivery. Combine this evidence with the real Kafka integration from step 6; identify precisely which components ran locally versus in AWS. Remove only run-created resources after verification, inspect Terraform state and independently audit cleanup. Record failures honestly and complete cleanup even if assertions fail.

**Done when:** Actual managed DynamoDB writes/reads, recommendation correctness, scoped analytics and replay behavior have evidence; temporary resources are removed and cleanup verified. If access, cost or another required gate remains unresolved, leave this step unfinished and Phase 5 In Progress or Blocked as appropriate.

**Prompt:** `Do Phase 5 step 8 from "phase-5 steps.md" only: execute the reviewed temporary DynamoDB verification from step 7 and tear down its run-created resources afterward. Preserve the US$10 total cap and US$0.50 reserve; do not proceed if a required deployment gate is unresolved. Then stop.`

## 9. Verify acceptance and close Phase 5

Check every Phase 5 acceptance criterion against actual evidence. Run any outstanding relevant checks and fix demonstrated Phase 5 defects. Update README, service/API instructions and the roadmap to reflect actual behavior. Create `docs/progress/phase-5.md` within the required 200–300-word maximum, covering work/files, approved decisions, tests, limitations and next steps. Update architecture only for approved design changes. Mark Phase 5 Completed only if all scoped tasks and acceptance checks, including managed NoSQL use, pass; otherwise record remaining work accurately.

**Done when:** Evidence supports the recorded status, documentation is aligned, and the user receives a concise handoff. Phase 6 remains Not Started. Do not commit or push.

**Prompt:** `Do Phase 5 step 9 from "phase-5 steps.md" only: audit acceptance evidence, finish required verification and documentation, and record the accurate Phase 5 status. Do not start Phase 6, commit or push. Then stop.`

**Step 9 result (2026-11-11):** Acceptance criteria, local combined-demo evidence and managed
DynamoDB write/read/replay/cleanup evidence were audited. The 47-test suite, smoke checks and
documentation checks passed. Phase 5 is now Completed for its approved scope; Phase 6 remains
Not Started.
