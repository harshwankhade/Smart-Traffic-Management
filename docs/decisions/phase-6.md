# Phase 6 alert contract and delivery design

**Status: approved by the user (2026-11-11).** The user replied "OK I APPROVE" to the proposed Phase 6 design. Phase 1 already approved SQS Standard plus a DLQ, Python Lambda, DynamoDB on demand, one alert per high window, incident alerts on creation/status change, deterministic alert IDs, and an Incident Manager transactional outbox. Phase 6 implementation and cloud provisioning remain separate steps.

## Current seams

- Signal Recommendation consumes `traffic.results`, stores deterministic recommendations before committing Kafka offsets, and rejects changed-content replays. Its current write callback has no queue action.
- Incident Manager stores one `IncidentRow` per incident. Create and material updates commit directly; changed revisions receive a new UUID `event_id`. Resolved incidents cannot reopen. No outbox exists.
- Alert Service only handles the Phase 1 smoke event. `contracts/v1/alert.schema.json` already specifies the planned common alert fields but has no outcome or queue envelope. Phase 5 uses separate owner-scoped DynamoDB tables with conditional, idempotent writes.

## Proposed v1 contracts and identities

Use the existing alert schema fields as the **request body**: `schema_version`, `alert_id`, `source_type`, `source_id`, `intersection_id`, `reason`, `occurred_at`, `rule_version`. Add an explicit `alert-request.schema.json` and example; retain the existing `alert.schema.json` as the base alert identity contract unless an approved compatible extension is needed. UTC timestamps use RFC3339 `Z`. SQS carries one JSON request per message; its message ID is transport metadata, never the business identity.

| Source | Request rule | Stable identity |
|---|---|---|
| Congestion | Only a validated `high` window after the recommendation is durably stored | `source_id = window_id`; `alert_id = window_id + /congestion-alert/v1`; `occurred_at = window_end`; fixed reason code `high_congestion` |
| Incident | Creation and status changes only; description-only changes produce no alert | `source_id = incident event_id`; `alert_id = event_id + /incident-alert/v1`; `occurred_at = updated_at`; reason code includes incident type and current status |

The same source revision produces identical request bytes on retry. A status change gets a new incident event ID; an unchanged patch does not. Keep the request free of physical control or external notification fields. Validate IDs, source-specific semantics and payload size before enqueueing and in Lambda. The alert **outcome record** adds `outcome = recorded`, `processed_at`, and the original request fields; it records successful persistence, not guaranteed external notification. Define its own v1 schema/example during implementation. No public alert query API is proposed in this phase; DynamoDB read and logs provide inspection/demo evidence.

## Proposed producer delivery

Signal Recommendation stores first, then sends the high-window request to SQS, then commits the Kafka offset. On send failure or ambiguous acknowledgement, retry the same request without committing. Conditional recommendation storage and Lambda identity absorb replay; a changed-content result still quarantines under the Phase 5 policy. Readiness should reflect required queue unavailability while the worker is enabled.

Incident Manager adds an `alert_outbox` table in its own SQL schema with unique `alert_id`, immutable request JSON, creation time, sent time, attempt count and last error. Create or material update and outbox insert commit in **one SQL transaction**, retaining optimistic version checking. A description-only edit does not enqueue. A background task in the same service claims pending rows with a lease, sends with bounded backoff, and marks sent only after SQS acknowledgement. On ambiguous acknowledgement it retries the same request. Multiple workers must not concurrently claim the same row; lease expiry recovers a crashed worker. Do not mark an incident write failed merely because subsequent queue delivery fails; expose/log pending outbox state for diagnosis. SQL migration/bootstrap must cover both SQLite local and the prepared PostgreSQL schema.

## Proposed SQS, Lambda and storage behavior

- One SQS Standard source queue and one SQS Standard DLQ, both run-scoped in cloud tests; redrive after **5 receives**. Use a **60-second visibility timeout**, **10-second Lambda timeout**, batch size **5**, and `ReportBatchItemFailures` so only failed message IDs return to the queue. Review these values against actual Lambda/SQS constraints and measured handler duration before cloud apply.
- Lambda validates each message independently. A successful conditional DynamoDB write or identical existing record succeeds; a conflicting alert ID with changed payload is logged as a conflict and sent through the failure route for investigation. Transient DynamoDB failures return that item as failed. Malformed requests are logged without raw sensitive payload and returned as failed, then reach the DLQ. No exception should silently acknowledge an unpersisted request.
- Alert Service alone owns a `traffic_alerts` DynamoDB table, keyed by `alert_id` with no secondary index. Store the full request, outcome and processing timestamp. Use conditional insert plus strongly consistent comparison on an ambiguous/duplicate write. No TTL for required demo history. Grant the function only its table access and CloudWatch logging; grant each producer only queue send permission. Limit the event-source mapping's concurrency to control cost and repeated failures.
- Emit structured logs with `alert_id`, `source_type`, `source_id`, SQS message ID, outcome and error class. Exclude full request bodies and credentials. DLQ replay is an explicit operator action using the **same original body** after diagnosis; no ninth service or automatic unsafe rewrite.

## Proposed verification and cost gate

1. Local unit tests: schema/identity stability, no alert for non-high windows or description-only incident edits, transaction rollback, optimistic conflict, outbox crash/lease/ambiguous-send recovery, duplicate and conflicting DynamoDB writes, malformed/transient Lambda records, and partial-batch response.
2. Local integration/demo: use existing Kafka and DynamoDB Local plus a controllable SQS adapter or emulator; produce one high window and one incident, show two asynchronous alert records, duplicate replay, queue outage/recovery, and traceable logs. Record any emulation limits.
3. Terraform format/validate/mock and read-only plan for queue, DLQ, function, mapping, table, IAM and log group. Package Python 3.14 Lambda dependencies for Linux and verify the artifact before deployment.
4. Cloud acceptance requires a separate reviewed cost estimate and explicit temporary-deployment authorization under the current US$10 total cap (raised by user approval on 2026-11-12). Send both requests through actual SQS, observe Lambda invocations/logs and DynamoDB records, test replay plus one controlled failure/redrive, then destroy and audit run-owned resources. No full cloud system or Phase 7 work is implied.

## Step 2 implementation note

The separately authorized producer step adds a stable request builder and injectable SQS/local sender, opt-in high-window sending after recommendation persistence, and an Incident Manager outbox committed with the incident revision. SQLite creates the outbox table automatically; initial PostgreSQL DDL and an existing-schema upgrade script are prepared but not applied. A worker claims rows with expiring leases, retries after outage or ambiguous acknowledgement, and marks sent only after send acknowledgement. No Lambda, alert outcome store or cloud queue was created in this step.

## Step 3 implementation note

The separately authorized Alert Service step adds a standard-library request validator, SQS partial-batch handler, conditional DynamoDB alert repository, and `recorded` outcome contract. Identical deliveries reuse the original logical record; malformed, conflicting and transiently failed items appear in `batchItemFailures`. Structured logs identify alert/source/message IDs and the outcome without logging bodies. The self-contained and DynamoDB Local demos both passed with three simulated queue messages and two logical alerts. The local container/network were removed after verification; its volume was retained. No AWS queue, Lambda function, IAM policy or trigger was created.

## Step 4 preparation note

The separately authorized IaC step prepares a guarded, run-scoped Terraform root for SQS/DLQ, the Alert Service Lambda and trigger, alert DynamoDB table, CloudWatch log group and scoped IAM. Producer send policies remain unattached until workload identities are deployed. A local Python 3.14 ZIP builder bundles the handler, repository, shared storage helper and pinned pure-Python Boto3 dependencies. Terraform formatting, validation and two mock plan tests passed; ZIP build/import checks passed. No real AWS plan, apply or billable resource was created. Cloud invocation and teardown remain Step 5.

## Approval and execution boundary

The user approved the identities, request/outcome contracts, incident outbox semantics, retry/DLQ settings, DynamoDB key/ownership, and test plan on 2026-11-11. This approval settles the design; Steps 2–5 in `phase 6 steps.md` each require their own prompt, and billable provisioning requires explicit authorization.
