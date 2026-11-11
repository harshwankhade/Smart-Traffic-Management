# Phase 5 local combined-demo evidence

Date: 2026-11-11. Environment: pre-existing local Docker Kafka at `127.0.0.1:9092` and a
local-only DynamoDB Local 2.6.1 container at `127.0.0.1:8000`. No AWS request, Terraform apply,
or cloud resource was involved.

Commands actually run:

```powershell
.venv\Scripts\python scripts\phase5_local.py up
.venv\Scripts\python scripts\phase5_local.py bootstrap
$env:PHASE5_LOCAL_DEMO = '1'
.venv\Scripts\python -m unittest tests.test_phase5_demo -v
.venv\Scripts\python -m unittest discover -s tests -v
.venv\Scripts\python scripts\smoke.py
```

The first bootstrap request met DynamoDB Local during JVM startup and received a transient
closed connection; rerunning bootstrap verified both approved tables. The helper now retries
that transient condition. The combined demo then passed in 62.057 seconds. It used one unique
`p5-demo-...` ID, published a valid high-congestion result to `traffic.results`, verified that
both owners persisted it, and read both API detail routes. Its literal check confirmed
`extend_green`, `green_extension_seconds: 10`, and `simulated: true`. Repeating the result
raised both duplicate counters while each API list still had one item. After both temporary
service processes restarted, each API still returned the stored record. The test removed its
own records and no demo-owned Python process remained.

Regression results: 47 unit tests passed with five explicitly opt-in integrations skipped; all
eight smoke entry points passed. Limitation: this confirms only the loopback Kafka/DynamoDB path;
it does not substitute for the separately completed managed DynamoDB evidence.
