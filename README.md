# Smart Traffic Management (S12)

This academic project simulates traffic monitoring at intersections. It accepts sensor readings, computes congestion windows, recommends **simulated** signal changes, records incidents, and creates alerts. It never controls real traffic signals.

The eight application services are Sensor Registry, Traffic Ingestion, Event Publisher, Congestion Processor, Signal Recommendation, Incident Manager, Alert Service, and Traffic Analytics. Six run on EKS in the cloud design; Congestion Processor runs Apache Flink on EMR, and Alert Service runs on Lambda. [The design document](docs/DESIGN_DOCUMENT.md) explains their responsibilities and connections.

## Prerequisites

Use **PowerShell from the repository root** for the commands below. The documented Windows setup uses Python 3.14 and JDK 17 or newer. The local Flink build was tested with Maven 3.9.11 and JDK 21 targeting Java 17.

| What you want to run | Additional tools |
|---|---|
| Python tests, smoke check, Phase 2 HTTP demo | Python 3.14 and JDK 17+; no Docker or AWS account needed |
| Kafka, Flink, DynamoDB Local, or ZooKeeper demos | Docker Desktop running; Maven for the Flink demo |
| Cloud deployment and observability | AWS CLI/profile, Terraform, Docker, `kubectl`, access to the approved AWS account and Git repository; follow the reviewed runbooks |

## 1. Install Python dependencies

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python -m pip check
```

`requirements-lock.txt` is the tested Windows dependency set. `.env.example` lists service configuration variables, but the scripts **do not automatically load** `.env` files. Set a needed variable in the terminal that launches its service. Local demos create their own loopback configuration under the ignored `.data/` directory.

## 2. Run checks and the simplest demo

```powershell
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python scripts\smoke.py
.venv\Scripts\python scripts\demo_phase2.py
```

The test suite runs its standard local checks; opt-in Docker integrations are skipped unless explicitly enabled. The smoke check starts and stops all eight service entry points; it needs `java` and `javac` on `PATH`. The Phase 2 demo exercises real Registry and Incident Manager HTTP requests, a dependency outage, and process restarts. It writes persistent demo records under `.data/demo-phase2/` and does not use AWS.

### Start individual HTTP services

For manual exploration, open two PowerShell terminals at the repository root and run one command in each:

```powershell
.venv\Scripts\python scripts\run_service.py sensor-registry
```

```powershell
.venv\Scripts\python scripts\run_service.py incident-manager
```

Open Registry API docs at `http://127.0.0.1:8001/docs` and Incident Manager API docs at `http://127.0.0.1:8006/docs`. Stop each with Ctrl+C. Their default SQLite databases are `.data/registry.db` and `.data/incidents.db`, so records survive a process restart. Other local ports are Ingestion `8002`, Publisher HTTP `8003`, Recommendation `8005`, and Analytics `8008`. `run_service.py SERVICE --port NUMBER` overrides a port; all manual services bind to loopback. See the [Phase 2 API guide](docs/phase-2-api.md) for request examples. `/healthz` is a liveness check, not proof that dependencies are ready.

## 3. Run local integration demos

Start Docker Desktop first. These demos use loopback containers and synthetic data. Run one demo at a time because some share Kafka or DynamoDB Local. Normal `down` commands stop their containers and networks **without deleting named volumes**.

### Ingestion → gRPC Publisher → Kafka and archive

```powershell
.venv\Scripts\python scripts\generate_proto.py
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\phase3_local.py up
.venv\Scripts\python scripts\phase3_local.py bootstrap
.venv\Scripts\python scripts\demo_phase3.py --failure-tests
.venv\Scripts\python scripts\phase3_local.py down
```

`configure` creates local-only archive credentials under `.data/phase3/local.env`; it does not use AWS keys. The demo starts its own service processes, validates sensor references, checks actual Kafka records and archived bytes, and exercises retries and outages. See the [Phase 3 guide](docs/phase-3-api.md). If you will run Phase 4 immediately afterward, keep the Phase 3 containers running and use `phase3_local.py down` only after Phase 4 is stopped.

### Stateful Flink congestion windows

```powershell
mvn -f services/congestion-processor/pom.xml package
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\phase4_local.py up
.venv\Scripts\python scripts\demo_phase4.py --report .data/phase4-demo.json
.venv\Scripts\python scripts\phase4_local.py down
.venv\Scripts\python scripts\phase3_local.py down
```

`phase4_local.py up` starts and bootstraps its Kafka dependency and the local Flink cluster. The demo compares known inputs with actual `traffic.results` records, checks duplicate and late readings, and restores a checkpoint. Flink's local UI is `http://127.0.0.1:8081` while the cluster is up. Stop Phase 4 before Phase 3; retained volumes preserve local data. See the [processing and recovery guide](docs/phase-4-processing.md).

### Recommendation and Analytics consumers 

```powershell
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\phase3_local.py up
.venv\Scripts\python scripts\phase4_local.py bootstrap
.venv\Scripts\python scripts\phase5_local.py up
.venv\Scripts\python scripts\phase5_local.py bootstrap
$env:PHASE5_LOCAL_DEMO = '1'
.venv\Scripts\python -m unittest tests.test_phase5_demo -v
Remove-Item Env:PHASE5_LOCAL_DEMO
.venv\Scripts\python scripts\phase5_local.py down
.venv\Scripts\python scripts\phase3_local.py down
```

This demo publishes a known result to Kafka, waits for both independent consumers, reads both HTTP APIs, replays the result, and checks persistence after service restarts. It uses DynamoDB Local, not AWS DynamoDB. See the [Phase 5 demo guide](docs/phase-5-demo.md).

### Incident and congestion alerts 

The quickest alert demo needs no Docker:

```powershell
.venv\Scripts\python scripts\demo_phase6_alerts.py
```

It runs the real alert producers and handler with an in-memory queue/table stand-in. To use a real local DynamoDB table, follow the [Phase 6 local guide](docs/phase-6-local.md). Actual SQS → Lambda → DynamoDB evidence is recorded separately in the [Phase 6 cloud report](docs/progress/phase-6.md).

### ZooKeeper publisher failover

```powershell
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\demo_phase7.py --report .data/phase7-demo.json
```

The demo starts its own loopback services and Docker dependencies, then checks leader crash, successor election, session recovery, same-ID retry, Kafka records, and Analytics recovery events. It stops its service processes but retains supporting Docker containers and volumes for inspection. See [Phase 7 evidence](docs/evidence/phase-7-local.md) for results and limits. Publisher failover is bounded crash recovery; it does not guarantee exactly-once delivery or fence delayed in-flight Kafka writes.

## 4. Cloud deployment and monitoring

The cloud environment is **not** started by the local commands above. Terraform owns AWS infrastructure; Argo CD deploys and updates the Kubernetes services from Git. Do not deploy application manifests with direct `kubectl apply`. A cloud run requires a current resource/state and cost check, an exact reviewed Terraform plan, deployment authorization, and a supervised cleanup plan. Teardown has its own approval boundary; preserve Terraform state until an independent absence audit is complete.

These preparation checks render and validate local configuration without deploying it. Terraform `init` may download providers:

```powershell
terraform -chdir=infrastructure/terraform/phase8 init -backend=false -input=false
terraform -chdir=infrastructure/terraform/phase8 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase8 validate
.venv\Scripts\python scripts\phase8_package.py
kubectl kustomize deploy/gitops/apps
.venv\Scripts\python scripts\phase8_gitops_check.py
```

