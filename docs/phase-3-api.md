# Phase 3 API and local demo

## Setup

From project root in PowerShell, after starting Docker Desktop:

```powershell
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python scripts\generate_proto.py
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\phase3_local.py up
.venv\Scripts\python scripts\phase3_local.py bootstrap
.venv\Scripts\python scripts\demo_phase3.py --failure-tests
```

The integration demo starts its own Registry, Publisher and Ingestion processes on temporary ports, registers a sensor, submits readings, compares actual Kafka records with archived bytes, verifies failures/retries and restarts processes/containers. It stops its application processes and retains supporting containers/volumes. Failure tests stop and restore only containers belonging to `smarttraffic-phase3`; do not run another demo against those same containers concurrently.

The credentials file `.data/phase3/local.env` is ignored and local-only. Do not copy AWS keys into it. `configure` preserves existing credentials; changing them without coordinating retained object-store data can prevent access. Normal `phase3_local.py down` stops/removes these containers and their Compose network, retaining named volumes. No volume-deletion option is provided.

## Manual API use

Start each in a separate terminal from the project root:

```powershell
.venv\Scripts\python scripts\run_service.py sensor-registry
.venv\Scripts\python scripts\run_service.py event-publisher --phase3-local
.venv\Scripts\python scripts\run_service.py traffic-ingestion --phase3-local
```

Registry is at port 8001, Ingestion 8002, Publisher HTTP 8003 and Publisher gRPC 50051. All default bindings are loopback. The flag explicitly loads local archive/Kafka configuration; `.env` is not automatically loaded. Override Registry, Publisher target or HTTP readiness URLs using the variables in `.env.example` before launching the relevant service. For ephemeral Publisher gRPC binding `127.0.0.1:0`, its successful `/readyz` response reports the selected `grpc_port`.

Register an active sensor and its intersection as described in the [Phase 2 API](phase-2-api.md), then submit:

```powershell
Invoke-RestMethod http://127.0.0.1:8002/readings -Method Post -ContentType application/json -Body '{"schema_version":"1.0","event_id":"reading-demo-0001","sensor_id":"sensor-demo","intersection_id":"int-demo","observed_at":"2026-11-09T10:00:00Z","vehicle_count":12,"average_speed":18.5,"occupancy":0.72}'
```

202 response: `{"event_id":"reading-demo-0001","accepted":true}`. Both archive and Kafka have acknowledged at that point; congestion processing is not implemented. Repeating identical content is allowed and may republish to Kafka. Changing content under that ID returns 409. Generate a fresh ID for a genuinely different observation; preserve the same ID/content when retrying an uncertain attempt.

At least one measurement is required; absent fields are omitted rather than null. Counts must fit signed 64-bit integers; speed is km/h, occupancy is in [0,1]. Unknown/blank fields, nonfinite numbers and numeric strings are rejected. Timestamps use UTC `Z`; canonicalization preserves the instant and sub-microsecond precision. Sensor must exist, be active and match the intersection. No deletion, queryable reading database or windowing endpoint is added.

| HTTP | Meaning |
|---|---|
| 202 | Archive persisted and Kafka delivery callback succeeded |
| 422 | Invalid measurement/schema, unknown/inactive sensor or intersection mismatch |
| 409 | Archived event ID reused with different canonical content |
| 503 | Dependency unavailable, publication uncertain or deadline elapsed; retry same ID/content |
| 500 | Unexpected failure or invalid Publisher acknowledgement |

Errors use `detail` and include the event ID when available. Validation errors omit raw invalid values to safely report NaN/Infinity. `/healthz` preserves its original liveness payload; `/readyz` returns 503 if dependencies are unavailable. Readiness is a point-in-time check, not a publication or availability guarantee.

## Generator and inspection tools

```powershell
.venv\Scripts\python scripts\generate_readings.py --seed 12 --count 5
.venv\Scripts\python scripts\inspect_phase3.py consume --event-id reading-demo-0001
.venv\Scripts\python scripts\inspect_phase3.py archive --event-id reading-demo-0001
```

The generator has fixed timestamps/seed/ID prefix; reuse its inputs deliberately for retry tests. The consumer inspects the existing one-partition topic from the beginning without committing offsets or creating topics. It displays keys/offsets and payloads. Archive inspection fetches actual stored bytes through S3, not a filesystem fake. Existing records are retained across normal restarts; test runs use unique prefixes to distinguish their evidence.

## Delivery limits

See the [approved decision record](decisions/phase-3.md). Archive-first delivery is not atomic with Kafka. Archive-only records can remain after failure; same-ID retry can finish publication. Lost responses/restarts can produce duplicates. Single-process locking does not protect against overlapping publisher processes or provide the Phase 7 failover guarantee. Internal gRPC and Kafka are plaintext only for local loopback development; AWS adapter configuration uses MSK IAM/TLS and the SDK credential chain, but cloud integration/security is unverified.
