# Smart Traffic Management - S12

Phase 5 is complete for its approved scope. The user approved the derived-record/query/delivery design in
`docs/decisions/phase-5.md`; Steps 1–5 added recommendation and summary contracts, pure
simulation-only rules, service-owned DynamoDB repositories, independent Kafka result
consumers and read-only REST queries verified locally. The combined local
[Kafka-to-DynamoDB-to-HTTP demo](docs/phase-5-demo.md) also passed. A temporary AWS DynamoDB run verified repository
replay behavior and both AWS-backed APIs, then removed all run-owned resources; see
[the managed verification evidence](docs/evidence/phase-5-managed.md).
All Phase 5 acceptance criteria now have evidence, including managed DynamoDB use and cleanup.
Phase 6 Steps 2–3 are implemented locally: Incident Manager stages alerts in its SQL outbox,
Signal Recommendation sends high-congestion requests, and the Alert Service SQS batch handler
stores idempotent outcomes in its own DynamoDB table. Queue delivery is opt-in with
`PHASE6_ALERTS_ENABLED=1` and `ALERT_QUEUE_URL` (and the Phase 5 consumer enabled for
recommendations). Run the [local alert demo](docs/phase-6-local.md) to exercise both paths.
Cloud queue/function provisioning and actual Lambda invocation were verified in a temporary Phase 6 AWS run and then removed; see [Phase 6 cloud evidence](docs/evidence/phase-6-cloud-attempt-4.md).
The guarded [Phase 6 Terraform root](infrastructure/terraform/phase6/README.md) and
Python 3.14 Lambda ZIP builder are verified; the temporary resources were destroyed after acceptance. See [the Phase 6 progress report](docs/progress/phase-6.md).

**Phases 1-3 are complete for their approved local/preparation scope. Phase 4 is complete: local Flink and a temporary Amazon EMR on EC2 job produced verified Kafka results and restored an S3 checkpoint. The cloud stack was torn down.** The system remains an academic simulation; no physical signal control occurs.

Read [requirements](PROJECT_BRIEF.md), [architecture](ARCHITECTURE.md), [roadmap](ROADMAP.md), and the [Phase 2 decisions](docs/decisions/phase-2.md). Root documents are authoritative; their `docs/` counterparts are location pointers.

To repeat the Phase 7 local check from the project root with Docker Desktop running:

```powershell
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\demo_phase7.py --report docs\evidence\phase-7-local.json
```

The demo starts its loopback dependencies, uses a unique ZooKeeper election path, stops its own service processes and retains Docker volumes. Its ZooKeeper stop/restart tests session recovery; see the evidence file for measured results and limits.

## Implemented locally

- Sensor Registry: intersection/sensor create, read and update with persistent SQL data.
- Incident Manager: REST-validated intersections, creation, description/status updates and terminal resolution. Incident event IDs/timestamps are server-owned; no alerts are published.
- Separate SQLAlchemy models and SQLite files, database constraints and optimistic incident update checks.
- Traffic Ingestion validates active sensors and calls Event Publisher through real gRPC; Publisher archives normalized JSON before acknowledged Kafka delivery.
- Local Kafka/SeaweedFS containers persist records/objects. Congestion Processor runs real Flink minute windows, bounded deduplication and checkpoint recovery. Signal Recommendation and Traffic Analytics consume its results and expose local read APIs; Alert Service retains Phase 1 health/smoke behavior.
- Versioned response schemas, local HTTP restart demo, automated tests and private RDS Terraform prepared for mocked checks only.

See [REST contracts, errors and examples](docs/phase-2-api.md) and [Flink processing/recovery](docs/phase-4-processing.md). Registry, Incident Manager and Ingestion expose local `/docs` and `/openapi.json`; Publisher exposes gRPC plus HTTP liveness/readiness. Queue delivery has temporary-cloud evidence. Phase 7 ZooKeeper crash and session recovery passed the [real local demo](docs/evidence/phase-7-local.md). Integrated cloud deployment and dashboards remain future work.

## Phase 4 local Flink demo

Build the Java-17-targeted job using Maven 3.9.11, then run the actual Java 17 Flink container demo:

```powershell
mvn -f services/congestion-processor/pom.xml package
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\phase4_local.py up
.venv\Scripts\python scripts\demo_phase4.py --report docs/evidence/phase-4-verification.json
.venv\Scripts\python scripts\inspect_phase4.py --seconds 10
.venv\Scripts\python scripts\phase4_local.py down
```

The demo compares known inputs with real Kafka results, excludes late readings and duplicates,
restarts the Flink cluster and restores a retained checkpoint. Its job is canceled afterward;
dependency containers/data remain until explicit shutdown (volumes retained).
See [local evidence](docs/evidence/phase-4-verification.json),
[managed evidence](docs/evidence/phase-4-cloud.json), [cleanup audit](docs/evidence/phase-4-cleanup.json),
[Phase 4 report](docs/progress/phase-4.md) and the
[EMR Terraform runbook](infrastructure/terraform/phase4-live/README.md).
Phase 4 evidence recorded AWS CLI and Boto3 authentication using the `smarttraffic-sdk` profile.
That profile is currently absent, so future managed work needs a fresh access check before use.
When available, set `AWS_PROFILE=smarttraffic-sdk` and `AWS_REGION=ap-south-1`; renew with
`aws login --profile smarttraffic` when needed. Earlier Amazon Managed Service for Apache Flink
attempts were rejected by account verification, so the user approved EMR on EC2 instead. Run
`stp4-91dd0a43a8` used Terraform to provision a private EMR 7.14/Flink 1.20 cluster, two-broker
MSK and S3. Both EMR verification steps completed: the job consumed `traffic.raw`, wrote the
expected minute-window records to `traffic.results`, then restored S3 checkpoint 1 and verified
the pending window and duplicate suppression. The run was interrupted during MSK provisioning;
the exact cluster was imported into its partial Terraform state before continuation. The cluster
terminated, the versioned run bucket was emptied, Terraform state is empty, the guard is disabled,
and an independent audit found no run-owned resources. See [Phase 4 decisions](docs/decisions/phase-4.md).
The written cost estimate was waived; actual billed cost and the unchanged US$5 ceiling were not
verified. This temporary processor test does not establish a complete cloud deployment. Phase 5
has started with approved design, pure rules, repositories, local Kafka consumers and
read-only recommendation/summary APIs.

## Setup and verification (PowerShell, project root)

Tested with Windows Python 3.14.6, JDK 21.0.11 and Terraform 1.16.1. Java smoke compilation targets release 17. Local application checks need neither AWS credentials nor Docker/Maven.

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python scripts\smoke.py
.venv\Scripts\python scripts\demo_phase2.py
.venv\Scripts\python -m pip check
```

`requirements.txt` pins API runtime dependencies; `requirements-dev.txt` adds schema test tools; `requirements-postgres.txt` adds the optional PostgreSQL driver. The full tested Windows environment is pinned in `requirements-lock.txt`. Linux packages and live PostgreSQL compatibility remain unverified. The installed Starlette version emits a deprecation warning for HTTPX-based TestClient usage; checks pass, and the runtime Registry HTTP client remains HTTPX.

The smoke runner uses temporary databases/loopback ports, checks all eight entry points and stops its own processes. The Phase 2 demo exercises real HTTP, Registry failure and actual process restarts. It uses new IDs per run and retains records in `.data/demo-phase2/`; `--data-dir PATH` selects another local directory. It does not touch manually running services.

## Run services manually

Run these in separate terminals:

```powershell
.venv\Scripts\python scripts\run_service.py sensor-registry
.venv\Scripts\python scripts\run_service.py incident-manager
```

Registry is at `http://127.0.0.1:8001/docs`; Incident Manager at `http://127.0.0.1:8006/docs`. Ctrl+C stops each service. Default databases are `.data/registry.db` and `.data/incidents.db`; restarts preserve records. Override using service-specific environment variables:

```powershell
$env:SENSOR_REGISTRY_DATABASE_URL = 'sqlite:///.data/registry.db'
$env:INCIDENT_MANAGER_DATABASE_URL = 'sqlite:///.data/incidents.db'
$env:SENSOR_REGISTRY_URL = 'http://127.0.0.1:8001'
```

Set variables in the terminal launching the relevant service. `.env.example` documents configuration; scripts do not automatically read `.env`. Absolute SQLite URLs avoid ambiguity when changing working directories. SQLite tables initialize automatically. PostgreSQL needs the separately documented bootstrap/migration step and service-specific credentials; runtime startup does not create PostgreSQL tables.

| Service | Default local port |
|---|---|
| Sensor Registry | 8001 |
| Traffic Ingestion | 8002 |
| Event Publisher | 8003 |
| Signal Recommendation | 8005 |
| Incident Manager | 8006 |
| Traffic Analytics | 8008 |

Use `--port NUMBER` to override, and adjust `SENSOR_REGISTRY_URL` accordingly. All manual services bind to loopback only. `/healthz` retains its original `scope: scaffold` payload for compatibility and is liveness only, not a database/dependency readiness check.

## Unapplied infrastructure

See [Terraform instructions](infrastructure/terraform/phase2/README.md) and [PostgreSQL bootstrap instructions](infrastructure/sql/README.md). Safe checks:

```powershell
terraform -chdir=infrastructure/terraform/phase2 init -backend=false -input=false
terraform -chdir=infrastructure/terraform/phase2 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase2 validate
terraform -chdir=infrastructure/terraform/phase2 test
```

Phase 2 Terraform checks use the mocked AWS provider and plan-only execution; its PostgreSQL
instance remains unapplied. The separate, user-authorized Phase 4 temporary stack was applied and
destroyed. Deployment approval defaults false. Provider downloads require Internet access; these
local checks require no AWS credentials.

The user-approved US$8 total cap and no-credit assumption remain binding, with approximately 20 minutes of
demonstration requested. The temporary Phase 4 EMR/MSK/S3 test verified that specific region,
runtime and private data path once, but actual billed cost and future capacity were not checked.
Linux packaging of the Python services and live PostgreSQL remain unverified. Team/deadline
remain unconfirmed. Any future cloud deployment requires separate authorization and cost review.

## Phase 3 real Kafka/archive demo

See [Phase 3 API/delivery instructions](docs/phase-3-api.md), [decisions](docs/decisions/phase-3.md) and [verification evidence](docs/evidence/phase-3-local.md). Start Docker Desktop before these commands:

```powershell
.venv\Scripts\python scripts\generate_proto.py
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\phase3_local.py up
.venv\Scripts\python scripts\phase3_local.py bootstrap
.venv\Scripts\python scripts\demo_phase3.py --failure-tests
```

This runs real local Apache Kafka 3.9.1 and persistent SeaweedFS 4.42 S3 storage, not AWS. The demo uses actual gRPC and consumes Kafka records/retrieves archived bytes. Duplicate Kafka records after retries are expected and reported; one event ID cannot silently overwrite different archived content. It exercises concurrent requests, process restarts, a lost response and dependency outages. Failed publication can leave an archive-only record. No exactly-once claim is made.

For manual operation, run Registry normally and launch Publisher/Ingestion with `--phase3-local`; see the API instructions for ports and environment overrides. `phase3_local.py down` stops only these supporting containers/network and retains volumes. No AWS account or credentials are needed for this local path.

Guarded [Phase 3 Terraform](infrastructure/terraform/phase3/README.md) defines MSK, the raw topic,
private S3 and IAM policies using Phase 2 network outputs. These resources were exercised in the
temporary Phase 4 EMR run and then destroyed. No standing cloud deployment is present; future
provisioning needs fresh authorization and a cost review.
