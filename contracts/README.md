# Versioned contracts

`v1/` contains approved record contracts and valid examples. Intersection, sensor and incident responses are implemented locally in Phase 2; reading/result/alert/gRPC workflows remain planned. See [Phase 2 API](../docs/phase-2-api.md) for narrower creation inputs, server-owned incident metadata and immutable fields. Record schemas are response contracts, not necessarily POST payloads.

JSON Schema 2020-12 validates structure and individual field ranges. Cross-record existence, window ordering, deterministic IDs and delivery guarantees need later application tests. `publisher.proto` drafts the approved Ingestion → Publisher path; its exact fields are approved as the initial v1 baseline. No generated stubs or RPC implementation are supplied in Phase 1.
