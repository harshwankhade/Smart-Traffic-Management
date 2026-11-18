# Versioned contracts

Phase 7 adds `recovery-event.schema.json`: an Analytics-owned, deterministic record of
publisher leader election and ZooKeeper session changes. It supports bounded recovery
evidence, not exclusive publishing or exactly-once delivery.

Phase 5 Step 2 adds `recommendation.schema.json` and `summary.schema.json` with examples.
The recommendation carries the complete source result, a deterministic ID, a simulated
action and a stable explanation. The summary preserves the result fields. Kafka consumers,
DynamoDB persistence and query APIs belong to later Phase 5 steps; see
`docs/decisions/phase-5.md`.

`v1/` contains approved record contracts and valid examples. Intersection, sensor and incident responses are implemented locally in Phase 2; reading publication and gRPC are implemented in Phase 3; result processing is implemented locally in Phase 4, with managed execution outstanding. Alerts remain planned. See [Phase 2 API](../docs/phase-2-api.md) and [result processing/recovery](../docs/phase-4-processing.md). Record schemas are response contracts, not necessarily POST payloads.

JSON Schema 2020-12 validates structure and individual field ranges. Cross-record existence, window ordering, deterministic IDs and delivery guarantees need later application tests. `publisher.proto` drafts the approved Ingestion → Publisher path; its exact fields are approved as the initial v1 baseline. Generated Python stubs and the actual Publisher RPC are supplied in Phase 3; regenerate with `scripts/generate_proto.py`. See `docs/phase-3-api.md` for delivery and retry semantics.
