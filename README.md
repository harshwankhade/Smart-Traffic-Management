# Smart Traffic Management - S12

**Phases 1 and 2: local foundation and domain APIs implemented. Cloud deployment and verification are deferred.** The system remains an academic simulation; no physical signal control occurs.

Read [requirements](PROJECT_BRIEF.md), [architecture](ARCHITECTURE.md), [roadmap](ROADMAP.md), and the [Phase 2 decisions](docs/decisions/phase-2.md). Root documents are authoritative; their `docs/` counterparts are location pointers.

## Implemented locally

- Sensor Registry: intersection/sensor create, read and update with persistent SQL data.
- Incident Manager: REST-validated intersections, creation, description/status updates and terminal resolution. Incident event IDs/timestamps are server-owned; no alerts are published.
- Separate SQLAlchemy models and SQLite files, database constraints and optimistic incident update checks.
- Six other application services retain their Phase 1 health/smoke entry points.
- Versioned response schemas, local HTTP restart demo, automated tests and private RDS Terraform prepared for mocked checks only.

See [REST contracts, errors and examples](docs/phase-2-api.md). These two services expose local `/docs` and `/openapi.json`; other scaffolds do not. No Kafka/Flink processing, queue delivery, ZooKeeper coordination, cloud deployment or dashboard has been implemented.

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

Both Terraform test runs use the mocked AWS provider and plan-only execution. No real AWS-backed plan or apply is authorized. Deployment approval defaults false. Provider downloads require Internet access; these checks require no AWS credentials.

The US$5 total cap and no-credit assumption remain binding, with approximately 20 minutes of demonstration requested. Cost/access/quotas are user-approved planning assumptions, not verified facts. Region/instance/engine availability, costs including setup/teardown/backups, IAM, private connectivity, Linux packaging and live PostgreSQL must be verified before provisioning. Team/deadline remain unconfirmed. Phase 3 requires separate authorization.
