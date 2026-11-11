# signal-recommendation

Phase 5 Step 2 adds pure rules in `recommendation/rules.py`. `recommend(result)`
validates a Phase 4 window and returns a deterministic, simulation-only recommendation.
High congestion suggests 10 additional green seconds; other levels suggest zero.
Step 4 adds an opt-in `traffic.results` consumer in group `signal-recommendation-v1`.
It validates the result, calculates a recommendation, persists it, then commits the offset.
Malformed results are logged and skipped; changed-content replay blocks at its offset.
`/readyz` reports dependency readiness and counters; `/healthz` retains its original
payload. Step 5 exposes read-only `GET /recommendations` and
`GET /recommendations/{recommendation_id}`. Both require `intersection_id`; the list
accepts UTC `from`/`to`, `limit`, and an opaque `cursor`. See `docs/phase-5-api.md`.

Step 3 adds `recommendation/repository.py`, which writes only the recommendation table
through DynamoDB. Set `DYNAMODB_ENDPOINT_URL=http://127.0.0.1:8000` for the local store;
omit it for AWS's normal credential chain. `RECOMMENDATIONS_TABLE` overrides the table name.
Conditional insertion returns `created` or `unchanged` for identical replay and raises
`RecordConflict` if the same window carries different content. The consumer uses this
repository when `PHASE5_CONSUMER_ENABLED=1`. Reads work with the consumer disabled if
the owned table is available. Local setup is in `docs/phase-5-api.md`; consumer setup
is in `docs/phase-5-consumers.md`. Local OpenAPI is available at `/docs`.

Approved placement: Kubernetes. See the root README for run and smoke-test commands.

Phase 6 Step 2 adds opt-in alert production. With `PHASE5_CONSUMER_ENABLED=1`, set
`PHASE6_ALERTS_ENABLED=1` and `ALERT_QUEUE_URL` to send one stable request for each
high-congestion result after recommendation storage and before Kafka offset commit.
Queue failures retry the same result without committing; non-high results send nothing.
The injectable in-memory sender supports local tests. The Lambda consumer is a later step.
