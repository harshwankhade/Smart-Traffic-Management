# Phase 5 local combined demo

This opt-in demo uses only loopback Docker dependencies. It sends a known, schema-valid
high-congestion Phase 4 result to Kafka, waits for both Phase 5 consumers, reads both real
HTTP APIs, repeats the result, and restarts both service processes before reading persisted
records again. It never creates AWS resources.

From the repository root in PowerShell:

```powershell
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\phase3_local.py up
# Keep the existing Phase 4 local Kafka topic setup; bootstrap Phase 4 if traffic.results is absent.
.venv\Scripts\python scripts\phase5_local.py up
.venv\Scripts\python scripts\phase5_local.py bootstrap
$env:PHASE5_LOCAL_DEMO = '1'
.venv\Scripts\python -m unittest tests.test_phase5_demo -v
Remove-Item Env:PHASE5_LOCAL_DEMO
```

`tests.test_phase5_demo` creates a unique `p5-demo-...` intersection ID, launches and stops
only its own loopback service processes, and removes only its own DynamoDB Local records. It
does not stop Kafka, archive, Flink, or a pre-existing DynamoDB Local container. When the
caller owns DynamoDB Local, it may later run `scripts\phase5_local.py down`; volumes are retained.

The test's literal expected outcome is `high` congestion -> `extend_green`, ten seconds and
`simulated: true`. It asserts one logical summary/recommendation after duplicate delivery and
performs API read-back after service restart. It is local evidence only; managed DynamoDB proof
is separately recorded in `docs/evidence/phase-5-managed.md`.
