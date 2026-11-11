# Phase 5 Step 5: recommendation and traffic summary REST APIs

The existing Signal Recommendation and Traffic Analytics services expose read-only APIs over
their own DynamoDB tables. These routes read persisted v1 records; they do not calculate a
recommendation or aggregate a window on request. Local OpenAPI pages are at `/docs` and
`/openapi.json` on each service.

| Service | List | Detail |
|---|---|---|
| Signal Recommendation | `GET /recommendations` | `GET /recommendations/{recommendation_id}` |
| Traffic Analytics | `GET /traffic/summaries` | `GET /traffic/summaries/{window_id}` |

Every request requires `intersection_id`, including detail lookup. It must be nonblank and at
most 128 characters. List requests accept `from`, `to`, `limit`, and `cursor`. `from` includes
windows whose **start** is at or after the bound; `to` excludes windows whose start is at or
after the bound. Bounds must be UTC RFC3339 timestamps ending in `Z`, including optional
fractional seconds, and `from` must precede `to`. Both bounds may be omitted. Results are
ascending by window start and window ID. `limit` defaults to 50 and must be 1–100. The
response is `{ "items": [<v1 records>], "next_cursor": <string or null> }`; an empty query
returns `items: []` and `next_cursor: null`. Pass the returned opaque cursor back with the
**same** intersection, time strings and limit. It represents the next DynamoDB page and is
not a stable snapshot if records change between calls. No table scan or cross-intersection
query is performed. Detail routes return one full v1 record.

Example requests, after running each service locally on port 8001/8002:

```text
GET http://127.0.0.1:8001/recommendations?intersection_id=I-1&from=2026-11-09T10:00:00Z&to=2026-11-09T11:00:00Z&limit=50
GET http://127.0.0.1:8002/traffic/summaries?intersection_id=I-1&limit=1
GET http://127.0.0.1:8002/traffic/summaries/I-1%2F2026-11-09T10%3A00%3A00Z%2F2026-11-09T10%3A01%3A00Z%2Fv1?intersection_id=I-1
```

Identifiers contain slashes, so encode them as one URL path value. `200` returns the page
or record; `404` means a detail record does not exist; `422` means a missing or invalid
query, malformed/mismatched cursor, or invalid identifier; `503` means the owned store is
unavailable. Stored numeric values are emitted as exact JSON numbers. The underlying
records and examples are in `contracts/v1/recommendation.schema.json`,
`contracts/v1/summary.schema.json`, and `contracts/v1/examples/`.

For local use, start and bootstrap DynamoDB Local with `scripts/phase5_local.py up` and
`bootstrap`, then set `DYNAMODB_ENDPOINT_URL=http://127.0.0.1:8000` in each service
process. `RECOMMENDATIONS_TABLE` and `SUMMARIES_TABLE` override the respective default
table names. Run `scripts/run_service.py signal-recommendation --port 8001` and
`scripts/run_service.py traffic-analytics --port 8002` in separate terminals. Set
`PHASE5_CONSUMER_ENABLED=1` if those processes should also ingest Kafka results; it is
off by default. See [consumer setup](phase-5-consumers.md) for Kafka configuration.

To reproduce the real HTTP check from the project root with Docker Desktop running:

```powershell
.venv\Scripts\python scripts\phase5_local.py up
.venv\Scripts\python scripts\phase5_local.py bootstrap
$env:PHASE5_DYNAMODB_API_TEST = '1'
.venv\Scripts\python -m unittest tests.test_phase5_api -v
Remove-Item Env:PHASE5_DYNAMODB_API_TEST
.venv\Scripts\python scripts\phase5_local.py down
```

The test uses unique intersection IDs, deletes only its own records, starts/stops only its
own API processes, and temporarily stops/restarts the Phase 5 DynamoDB container to test
outage handling. Avoid running it alongside other work using that local store. `down`
retains the named data volume.

**Reserved Phase 7 extension:** Traffic Analytics may later ingest and query distinct
`RecoveryEvent` records for ZooKeeper failover metrics. This API has no recovery-event
route, storage table, or ingestion path yet; its contract and ownership need Phase 7 work.
