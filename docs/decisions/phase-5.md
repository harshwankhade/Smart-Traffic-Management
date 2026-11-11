# Phase 5 interface and delivery decisions — proposed

Status: **approved by the user for Phase 5 steps 1–2** on 2026-11-11; Steps 3–5 were separately authorized and locally verified. This records the approved design for later Phase 5 steps. The requirements in the root `PROJECT_BRIEF.md`, approved baseline in `docs/decisions/phase-1.md`, Phase 4 processing contract and result schema remain authoritative.

## Verified prerequisites

- `contracts/v1/result.schema.json` requires one result per nonempty intersection window, with `window_id`, UTC bounds, reading count, optional numeric summaries and `low`/`medium`/`high`/`unknown` congestion. Flink emits `window_id = intersection_id/window_start/window_end/v1`. Its Kafka sink is at least once.
- Phase 4 local and temporary EMR evidence includes real `traffic.results` records and S3 checkpoint restore; the temporary cloud stack was removed. Neither Phase 5 service currently has business logic. Their `/healthz` response is the original scaffold liveness payload.
- Phase 1 approved DynamoDB on demand, deterministic derived upserts, and the simulated recommendation rule: high means +10 seconds of green; other levels mean no adjustment.

## Approved records, ownership and keys for later steps

| Record | Owner and source | Proposed identity and DynamoDB layout |
|---|---|---|
| `Recommendation` | Signal Recommendation alone, derived from one validated result | `recommendation_id = window_id + /recommendation/v1`; table `traffic_recommendations`, partition key `intersection_id`, sort key `window_start#window_id`; also store the full `window_id` and source result fields. |
| `TrafficWindowSummary` | Traffic Analytics alone, copied from one validated result without recomputing congestion | table `traffic_window_summaries`, partition key `intersection_id`, sort key `window_start#window_id`; full result fields and `window_id` are retained. |
| Future `Alert` | Alert Service in Phase 6 | Separate table/owner to be decided in Phase 6; Phase 5 does not create alert records. |
| Future `RecoveryEvent` | Traffic Analytics in Phase 7 | Reserved separate event type and storage/query contract; Phase 5 does not ingest or expose recovery events. |

Both Phase 5 tables use the primary key for scoped time queries; no secondary index is proposed. UTC `window_start` is canonical and lexically sortable. `window_end` is stored for display/filtering. The full `window_id` disambiguates any same-start events. Table names and capacity are environment configurable. No TTL is proposed for required history. Each service receives only its own table's read/write permissions. DynamoDB's numeric limits will be checked before writes; the existing Flink result contract allows arbitrary-precision count sums, so values beyond DynamoDB's numeric range must be rejected with an explicit error rather than silently truncated.

## Approved query API for step 5

- Signal Recommendation: `GET /recommendations/{recommendation_id}?intersection_id=...` and `GET /recommendations?intersection_id=...&from=...&to=...&limit=...&cursor=...`.
- Traffic Analytics: `GET /traffic/summaries?intersection_id=...&from=...&to=...&limit=...&cursor=...` and `GET /traffic/summaries/{window_id}?intersection_id=...`.
- `intersection_id` is mandatory for every query, including detail lookup, so a table scan is unnecessary. `from` is inclusive on window start; `to` is exclusive. Both are UTC RFC3339 `Z` timestamps. Defaults: no time bounds, ascending start order, limit 50, maximum 100. Cursor is opaque and scoped to the exact query parameters; malformed/mismatched cursor is rejected. Empty queries return an empty list. Detail routes return 404 when absent. No cross-intersection scan is used.

## Approved consumption, replay and failure policy for step 4

- Each service has an independent consumer group (`signal-recommendation-v1`, `traffic-analytics-v1`) on `traffic.results`, so both receive every window. Instance members in a group share partitions; no single global leader is needed. Environment may prefix group names for isolated local demos.
- Validate the full result schema and its semantic invariants before writing: canonical `window_id`, ordered minute bounds, finite numbers, and congestion consistent with provided speed/occupancy. Invalid records are logged with topic/partition/offset and skipped only after being recorded as a validation failure; no extra dead-letter service is added in Phase 5.
- Persist first, then commit the Kafka offset. After an uncertain write or commit failure, retry the same input. Same `window_id` and same canonical source content is an idempotent no-op. Same identity with changed source content is a conflict, not an overwrite; log and quarantine that partition/offset for investigation rather than advancing past it. A future intentional rebuild needs a separate approved policy. This preserves the Phase 4 stable-key at-least-once boundary.
- A transient DynamoDB failure pauses retries with bounded backoff and does not commit the offset. Readiness should fail while the required storage is unavailable; `/healthz` stays liveness-only.

## Approved output contracts and rules for step 2

- New v1 schemas `recommendation.schema.json` and `summary.schema.json`, plus examples. Existing schemas stay intact.
- Recommendation includes deterministic ID, intersection/window identity and time bounds, source result fields, `action = extend_green` or `no_adjustment`, `green_extension_seconds = 10` or `0`, and a stable reason code plus human-readable explanation. The action is explicitly simulated; there is no actuator address or command endpoint.
- Summary preserves the source result fields under a separate record contract, with the same stable `window_id`.
- Step 2 implements a pure result validator and recommendation rule in the Signal Recommendation service. It performs no Kafka or DynamoDB I/O. Tests cover every congestion level, missing measurements, malformed fields, boundary/identity mismatches and repeat input stability.

## Approval and execution boundary

The approved cloud products, service placement and +10-second rule needed no new approval. The proposed table key layout, public query routes, replay conflict handling and newly exposed record contracts are material interfaces. The user approved this proposal through the Step 1 approval question. Step 2 can add the schemas/examples, recommendation module and focused tests. Steps 3–9 remain separate prompts.

Expected step-2 files: `contracts/v1/recommendation.schema.json`, `contracts/v1/summary.schema.json`, their `examples/` files, `services/signal-recommendation/recommendation/` pure rule module, `tests/test_phase5_rules.py`, and concise contract/service documentation. No cloud resources or infrastructure files are changed in steps 1–2.

## Acceptance checks for steps 1–2

1. Every proposed interface and replay choice above has explicit approval or revision.
2. Both new examples validate against their own schemas; all existing v1 examples still validate.
3. Known high congestion yields +10 seconds; medium/low/unknown yield zero, with deterministic rationale and IDs.
4. Invalid result structure or identity is rejected, including inconsistent window boundaries and nonfinite measurements.
5. Identical input yields an identical recommendation; no side effects or Phase 3/4 behavior changes are introduced.

## Steps 1–2 result (2026-11-11)

The approved interfaces are recorded above. Step 2 added the two new v1 schemas/examples and
`services/signal-recommendation/recommendation/rules.py`. Pure validation checks exact v1 fields,
canonical 60-second UTC window identity, numeric ranges and a congestion level consistent with
the source measurements. The rule emits deterministic simulated guidance without I/O.

Verification actually run: `.venv\Scripts\python -m unittest tests.test_phase5_rules -v`
passed 4 tests; `.venv\Scripts\python -m unittest discover -s tests -v` passed 42 tests.
At that point, no Kafka/DynamoDB integration or cloud provisioning had run. Step 3 was
separately authorized afterward, with its result recorded below.

## Step 3 result (2026-11-11)

The two service-owned repositories use the approved `intersection_id` and
`window_start#window_id` keys. Shared storage code performs conditional insertion,
strongly consistent replay comparison, scoped ascending queries and pagination. It validates
DynamoDB numeric serialization before writing; unsupported large values fail explicitly.
The local Docker setup uses AWS's pinned DynamoDB Local 2.6.1 image with a retained volume
and two separate tables. No alert/recovery table or cloud resource was created.

Verification actually run: `scripts/phase5_local.py bootstrap` created/verified both local
tables. The opt-in `tests.test_phase5_storage` passed against real DynamoDB Local: writes/reads,
intersection and time isolation, pagination, identical replay, changed-content conflict,
numeric limit rejection and read after container restart. The normal Python suite passed
43 tests with the opt-in local integration test skipped; compile and whitespace checks passed.
The Step 3 container was stopped and its volume retained. See `docs/phase-5-storage.md` for
reproduction. Managed AWS DynamoDB, Kafka consumers and HTTP queries are not yet verified.

## Step 4 result (2026-11-11)

Both existing API services now start independent `traffic.results` workers only when
`PHASE5_CONSUMER_ENABLED=1`. The shared infrastructure loop uses separate approved groups,
validates each result, persists through the owning repository, then synchronously commits
the offset after checking the per-partition commit result. It retries storage/commit failures
without acknowledging the record. Invalid results are logged with Kafka location and skipped;
a conflicting replay is logged and quarantined without overwriting or advancing. The
original `/healthz` payload remains and `/readyz` checks worker state and the owned table.

The opt-in local Kafka/DynamoDB integration test passed, including duplicate replay,
invalid-record handling, storage outage, process restart recovery and conflict quarantine.
The normal 44-test suite passed with two opt-in container tests skipped; all eight smoke
entry points passed. See `docs/evidence/phase-5-consumers.md` and the runbook at
`docs/phase-5-consumers.md`. No AWS resource or Phase 5 query API was created.

## Step 5 result (2026-11-11)

Both services now expose the approved read-only list and detail routes. A shared API helper
normalizes UTC bounds to minute-start keys, emits exact DynamoDB numbers as JSON, and encodes
query-scoped opaque pagination cursors. Both routes require an intersection and use only the
owning repository. Invalid queries/cursors return 422, missing details return 404, and
unavailable storage returns 503. The actual HTTP and DynamoDB Local test passed isolation,
fractional time boundaries, pagination, empty results, exact numeric output, store outage
and recovery. The normal 45-test Python suite passed with three opt-in container tests
skipped; all eight smoke entry points passed. See `docs/phase-5-api.md` and
`docs/evidence/phase-5-api.md`. No AWS resource or Phase 7 recovery API was created.

## Managed DynamoDB preparation result (2026-11-11)

The separately authorized managed-DynamoDB preparation adds a guarded Terraform root with only
the two approved on-demand encrypted tables and two unattached, owner-scoped policies. A runner
will use the existing repositories and deterministic recommendation rule against uniquely named
AWS tables, then destroy only Terraform state-owned resources and confirm those exact tables and
policies are absent. Its mock tests passed; no AWS plan or apply ran. The documented
`smarttraffic-sdk` profile now passes STS/DynamoDB/Cost Explorer preflight and a read-only
AWS-backed plan. The plan has only the guard, two tables and two policies. Exact create/delete
permission and execution remain pending explicit approval. See
`docs/phase-5-managed-dynamodb.md` and `docs/evidence/phase-5-managed-preparation.md`.

## Step 8 result (2026-11-11)

The final managed run provisioned only two run-scoped DynamoDB tables and two unattached
owner policies. Existing repository/rule code wrote, read, queried and replayed known records;
both actual FastAPI APIs also returned paged, intersection-scoped AWS-backed data. The runner
destroyed all five state-owned resources, recorded empty state and absent exact names, and an
independent AWS CLI audit found no final-run leftovers. Two earlier test-run failures cleaned up
successfully and are documented with the final evidence. Managed DynamoDB acceptance is now
verified; the local end-to-end Step 6 demo passed and the final closure audit completed.

## Step 6 and closure result (2026-11-11)

The opt-in local combined demo published a unique valid result to the existing `traffic.results`
topic, verified both independent consumers and APIs, replayed the same result without duplicate
logical state, and read both records after restarting the service processes. The normal 47-test
suite (five opt-in checks skipped by default), all eight smoke checks and documentation checks
passed. Managed DynamoDB write/read/replay and cleanup evidence is recorded separately. Phase 5
is Completed for its approved scope; Phase 6 remains Not Started.
