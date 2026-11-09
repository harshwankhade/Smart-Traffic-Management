# Phase 2 REST API

Local-only interfaces. Run Registry on `127.0.0.1:8001` and Incident Manager on `127.0.0.1:8006`. Each exposes `/docs` and `/openapi.json`; `/healthz` retains the Phase 1 payload and means liveness, not dependency readiness.

## Routes

| Service | Method/path | Input | Response |
|---|---|---|---|
| Registry | `POST /intersections` | `intersection_id`, `name`, `location` | 201 intersection record |
| Registry | `GET /intersections/{id}` | Path ID | 200 intersection record |
| Registry | `PATCH /intersections/{id}` | `name` and/or `location` | 200 updated record |
| Registry | `POST /sensors` | `sensor_id`, `intersection_id`, `location`, `status` | 201 sensor record |
| Registry | `GET /sensors/{id}` | Path ID | 200 sensor record |
| Registry | `PATCH /sensors/{id}` | `location` and/or `status` | 200 updated record |
| Incident Manager | `POST /incidents` | `incident_id`, `intersection_id`, `type`, `description` | 201 full incident record |
| Incident Manager | `GET /incidents/{id}` | Path ID | 200 incident record |
| Incident Manager | `PATCH /incidents/{id}` | `description` and/or `status` | 200 incident record |

Create requests optionally include `schema_version: "1.0"`; responses always include it. Record schemas are in `contracts/v1/`. IDs are nonblank strings of at most 128 characters; use URL-safe IDs in the demo. Sensor status is `active` or `inactive`; incident type is `collision`, `closure` or `disruption`. Descriptions are nonblank and at most 2000 characters. Unknown fields are rejected. There are no deletion or collection-list endpoints.

Incident creation rejects client-supplied `event_id`, `status`, `reported_at` and `updated_at`. The server generates UUID event IDs, UTC RFC3339 timestamps ending in `Z`, and initial `open` status. These fields preserve the approved response schema; creation input is intentionally narrower. The event ID identifies the latest record revision and is not a retry/deduplication token for POST. Repeating a POST ID returns 409 rather than creating another row.

An incident may transition from `open` to `resolved`; reopening returns 409. Description changes are permitted in either state. Each actual change receives a new event ID/updated timestamp, preserving reported timestamp. Repeating an unchanged patch returns the same record. Empty patches, explicit nulls and changes to immutable fields return 422. Concurrent stale writes return 409; retrieve the current record before retrying.

## Errors

| Status | Meaning |
|---|---|
| 404 | Target intersection, sensor or incident is absent |
| 409 | Duplicate ID, prohibited transition or conflicting write |
| 422 | Invalid/extra/immutable fields, empty/null patch or unknown intersection reference |
| 503 | Database or Registry dependency unavailable, timed out or invalid |

Errors use FastAPI's `detail` field: a message string for application errors, or a validation error list for malformed inputs. Validation occurs before record lookup when payloads are malformed. Duplicate incident IDs are checked before the remote Registry call. Errors do not expose SQL or connection credentials.

Incident Manager looks up `GET /intersections/{id}` in Registry on creation. A 404 maps to 422; network/timeout, malformed data and other unsuccessful statuses map to 503. HTTPX connect/read/write/pool timeouts are each two seconds; this is not an end-to-end latency SLA. There is no automatic retry. Failed validation leaves no incident. Reading or updating an existing incident does not require Registry availability.

## Examples (PowerShell)

Start each service in its own terminal from the project root:

```powershell
.venv\Scripts\python scripts\run_service.py sensor-registry
.venv\Scripts\python scripts\run_service.py incident-manager
```

In another terminal:

```powershell
Invoke-RestMethod http://127.0.0.1:8001/intersections -Method Post -ContentType application/json -Body '{"intersection_id":"int-demo","name":"Demo","location":"North"}'
Invoke-RestMethod http://127.0.0.1:8001/sensors -Method Post -ContentType application/json -Body '{"sensor_id":"sensor-demo","intersection_id":"int-demo","location":"Lane 1","status":"active"}'
Invoke-RestMethod http://127.0.0.1:8006/incidents -Method Post -ContentType application/json -Body '{"incident_id":"inc-demo","intersection_id":"int-demo","type":"closure","description":"Simulated lane closure"}'
Invoke-RestMethod http://127.0.0.1:8006/incidents/inc-demo -Method Patch -ContentType application/json -Body '{"status":"resolved"}'
Invoke-RestMethod http://127.0.0.1:8001/sensors/sensor-demo
Invoke-RestMethod http://127.0.0.1:8006/incidents/inc-demo
```

Fixed example IDs conflict on a second run. Use `.venv\Scripts\python scripts\demo_phase2.py` for a repeatable, self-contained real-HTTP demo with fresh IDs, failure checks, process restarts and persisted records. It stops only processes it starts and retains its own database files under `.data/demo-phase2/`. Existing manually started services are not used or stopped.
