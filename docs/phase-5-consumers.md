# Phase 5 Step 4: result consumers

Signal Recommendation and Traffic Analytics now run independent consumers of the real
`traffic.results` topic. They use their own approved group IDs and their own DynamoDB tables.
Both validate the full result and semantic window identity. Signal Recommendation applies the
approved simulated rule; Analytics stores the result without recalculating congestion.
The worker writes first, then synchronously commits the Kafka offset. Identical replay is a
no-op in the repository. A changed record under the same window ID is logged and quarantines
that partition/offset; readiness becomes 503 until the operator resolves it. Storage failure
retries the same result with bounded backoff and no offset commit. Invalid JSON or result
content is logged with topic/partition/offset and then committed so a later valid result can
proceed. These actions are visible through process logs and `/readyz` counters.

The consumer is enabled only when `PHASE5_CONSUMER_ENABLED=1`; otherwise both applications
retain the original health-only behavior. The default groups are
`signal-recommendation-v1` and `traffic-analytics-v1`. `PHASE5_CONSUMER_GROUP_PREFIX` can
isolate a local test. `PHASE5_KAFKA_OFFSET_RESET` defaults to `earliest`; `latest` is used
only by the opt-in test so old retained demo records do not enter its new groups.
`KAFKA_BOOTSTRAP_SERVERS`, `KAFKA_RESULTS_TOPIC` and `KAFKA_AUTH_MODE` follow existing
Kafka configuration. `DYNAMODB_ENDPOINT_URL` is the explicit loopback-only local mode.

From the project root with Docker Desktop running:

```powershell
.venv\Scripts\python scripts\phase3_local.py configure
.venv\Scripts\python scripts\phase3_local.py up
.venv\Scripts\python scripts\phase4_local.py bootstrap
.venv\Scripts\python scripts\phase5_local.py up
.venv\Scripts\python scripts\phase5_local.py bootstrap
$env:PHASE5_KAFKA_DYNAMO_TEST = '1'
.venv\Scripts\python -m unittest tests.test_phase5_consumers -v
Remove-Item Env:PHASE5_KAFKA_DYNAMO_TEST
.venv\Scripts\python scripts\phase5_local.py down
```

The test starts and stops only its own API service processes, uses unique intersection and
consumer-group IDs, and deletes only its own DynamoDB records. It stops/restarts the Phase 5
DynamoDB container to verify an uncommitted result survives a storage outage and process
restart; avoid running it alongside other work using that local store. It leaves Phase 3
Kafka/archive containers and their data untouched. `phase5_local.py down` retains its volume.
For manual consumer runs, set `PHASE5_CONSUMER_ENABLED=1` and
`DYNAMODB_ENDPOINT_URL=http://127.0.0.1:8000` in each service terminal, then run
`scripts/run_service.py signal-recommendation` or `traffic-analytics`. `/readyz` requires
Kafka assignment and a live owned DynamoDB table. The original `/healthz` payload remains
liveness-only. Recommendation and summary query routes are documented in
[Phase 5 API usage](phase-5-api.md).

This is local Kafka/DynamoDB evidence only. Managed AWS DynamoDB, Kubernetes deployment,
GitOps and the full cloud application remain unverified.
