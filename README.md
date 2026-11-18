# Smart Traffic Management (S12)

An academic, cloud-native simulation that turns intersection sensor readings into congestion summaries, **simulated** signal recommendations, and incident alerts. It does not control real traffic signals.

## How it works

`Sensor Registry → Traffic Ingestion → Event Publisher → Kafka traffic.raw → Flink Congestion Processor → Kafka traffic.results → Signal Recommendation + Traffic Analytics`

Incident Manager and Signal Recommendation send alert requests through SQS to the Lambda Alert Service. ZooKeeper elects the active Event Publisher and supports a demonstrated crash-takeover flow.

| Runtime | Application services |
|---|---|
| Amazon EKS | Sensor Registry, Traffic Ingestion, Event Publisher, Signal Recommendation, Incident Manager, Traffic Analytics |
| Amazon EMR | Congestion Processor (Apache Flink) |
| AWS Lambda | Alert Service |

The cloud design also uses MSK, RDS PostgreSQL, DynamoDB, S3, SQS, Terraform, Argo CD, Prometheus, and Grafana. See the [design document](docs/DESIGN_DOCUMENT.md) for diagrams, responsibilities, and design choices.

## Project status

An integrated AWS run demonstrated the eight-service traffic and alert flows, GitOps deployment, and ZooKeeper takeover. A later certificate-validating HTTPS request succeeded. Phase 9 evidence shows both Ingestion and Analytics scaling to four replicas under sustained load, and live application metrics after the image repair. The load test exceeded its configured p95 latency threshold (5.47 s versus 2 s), and centralized Flink container logs remain unverified. The dated evidence does not establish the **current** AWS runtime or billing state.

See [Phase 8 acceptance](docs/evidence/phase-8-acceptance.md), [Phase 9 run evidence](docs/evidence/phase-9-step3-run.md), and the [roadmap](ROADMAP.md). Some phase status text in the roadmap predates the Phase 9 evidence.

## Run local checks (PowerShell)

Use Python 3.14 and JDK 17 or newer. From the project root:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements-lock.txt
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python scripts\smoke.py
.venv\Scripts\python scripts\demo_phase2.py
```

These commands use local services and do not create AWS resources. The Phase 2 demo stores its local records under `.data/demo-phase2/`. Docker Desktop is needed for the Kafka, Flink, DynamoDB Local, and ZooKeeper demos; follow the [Phase 3](docs/phase-3-api.md), [Phase 4](docs/phase-4-processing.md), [Phase 5](docs/phase-5-demo.md), [Phase 6](docs/phase-6-local.md), and [Phase 7](docs/evidence/phase-7-local.md) guides.

## Documentation

- [Requirements](PROJECT_BRIEF.md) and [technical architecture](ARCHITECTURE.md)
- [Design document](docs/DESIGN_DOCUMENT.md) and [phase roadmap](ROADMAP.md)
- [Deployment and GitOps guide](deploy/gitops/README.md) and [Terraform runbook](infrastructure/terraform/phase8/README.md)

Cloud provisioning and teardown have separate approval and cost gates. Check the current plan, spend, and resource state before any cloud operation.
