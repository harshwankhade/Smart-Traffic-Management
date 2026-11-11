# Phase 6: actionable steps

Run one numbered step per prompt. Each step includes its own focused checks and documentation. Do not begin the next step automatically. The existing eight-service boundary, US$5 total cap, and separate authorization for billable cloud resources remain in force.

1. **Settle the Phase 6 contract and delivery design.** Inspect the current Incident Manager, Signal Recommendation, Alert Service scaffold, Phase 5 storage conventions, and Phase 1 decisions. Specify and obtain approval for the v1 alert request/record schemas, deterministic IDs, SQS Standard + DLQ retry behavior, Lambda partial-batch handling, DynamoDB alert ownership, incident transactional outbox, and local/cloud test plan. Record approved choices in `docs/decisions/phase-6.md`. This step changes no runtime behavior or cloud resources.

2. **Implement the two alert producers.** Emit one stable request for each high-congestion window from Signal Recommendation. In Incident Manager, atomically save incident changes and outbox entries for creation and material status changes; retry queue delivery and mark an entry sent only after acknowledgement. Add local queue adapters and focused tests for duplicate input, queue outage, restart, and unchanged incident updates. Do not deploy cloud resources.

3. **Implement the Alert Service.** Turn the existing Lambda scaffold into an SQS-triggered handler that validates both request types, writes an idempotent alert outcome to its own DynamoDB table, and emits traceable logs. Handle malformed records, repeat delivery, transient storage errors, and partial-batch retries according to Step 1. Add local handler/repository tests and a reproducible local end-to-end demo for congestion and incident paths.

4. **Prepare and verify IaC.** Add guarded Terraform for the alert queue, DLQ, Lambda package/function, SQS event-source mapping, DynamoDB alert table, logging, and least-privilege permissions. Run formatting, validation, mocked/plan-only checks, and package checks. Document deploy and teardown commands. Do not apply or create billable resources in this step.

5. **Run the authorized cloud acceptance and close Phase 6.** After a reviewed cost estimate and explicit deployment authorization, provision only the Phase 6 resources needed for a temporary test. Invoke both alert paths through SQS, inspect actual Lambda logs and DynamoDB outcomes, exercise duplicate/retry/DLQ recovery, capture evidence, and tear down/audit run-owned resources. Run relevant regression checks; update `README.md`, `docs/progress/phase-6.md`, and the Phase 6 roadmap status only to the extent supported by results. Stop before Phase 7.

If cloud access or spending authorization is unavailable, complete the local and plan-only work, record the cloud acceptance gap, and leave Phase 6 In Progress or Blocked rather than Completed.
