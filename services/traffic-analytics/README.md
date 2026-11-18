# traffic-analytics

## Phase 7 recovery events

Traffic Analytics owns a separate `traffic_recovery_events` table and exposes
`GET /traffic/recovery-events?publisher_id=...` plus a scoped detail route. The publisher
posts compact v1 events only when `RECOVERY_EVENTS_ENABLED=1`; set `TRAFFIC_ANALYTICS_URL`
to the Analytics service base URL. Event persistence failures are logged and counted by the
publisher but do not make an elected publisher accept work when ZooKeeper is unavailable.
Run `scripts/phase5_local.py bootstrap` once to create the local recovery table.

Phase 5 Step 2 adds the `contracts/v1/summary.schema.json` record contract for
persisting Phase 4 results. Step 4 adds an opt-in `traffic.results` consumer in group
`traffic-analytics-v1`. It validates and persists the result without recomputing congestion,
then commits the offset. Malformed results are logged and skipped; changed-content replay
blocks at its offset. `/readyz` reports dependency readiness and counters; `/healthz`
retains its original payload. Step 5 exposes read-only `GET /traffic/summaries` and
`GET /traffic/summaries/{window_id}`. Both require `intersection_id`; the list accepts
UTC `from`/`to`, `limit`, and an opaque `cursor`. See `docs/phase-5-api.md`.

Step 3 adds `analytics/repository.py`, which writes only the summary table through DynamoDB.
Set `DYNAMODB_ENDPOINT_URL=http://127.0.0.1:8000` for local verification; omit it for
AWS's normal credential chain. `SUMMARIES_TABLE` overrides the table name. Conditional
insertion is idempotent for identical replays and rejects changed content under the same
window key. The consumer uses this repository when `PHASE5_CONSUMER_ENABLED=1`.
Reads work with the consumer disabled if the owned table is available. See
`docs/phase-5-api.md` for local setup and checks; `/docs` serves local OpenAPI.

Approved placement: Kubernetes. See the root README for run and smoke-test commands.
