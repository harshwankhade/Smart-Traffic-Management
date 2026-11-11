# Phase 5 Step 3: local DynamoDB storage

Two service-owned repositories persist approved v1 records in separate DynamoDB tables.
Each table has `intersection_id` (partition key) and `window_key` (sort key, formatted
`window_start#window_id`). No secondary index, table scan, TTL, alert record or recovery-event
write is involved. The shared `traffic_contracts.dynamo_store` module handles only DynamoDB
operations; record ownership stays with each service. Same-key identical replay is unchanged;
changed content raises `RecordConflict` without overwriting the first record. A failed
conditional write is followed by a strongly consistent read to classify that result.

The repositories accept canonical minute boundaries for their internal time query. The
Step 5 REST APIs normalize arbitrary UTC `from`/`to` instants to the correct minute
boundaries before calling them. The lower bound is inclusive and upper bound exclusive.
Results are ascending and paged with DynamoDB's `LastEvaluatedKey`; Step 5 encodes that
key as an opaque query-scoped API cursor. See [API usage](phase-5-api.md).

From the project root with Docker Desktop running:

```powershell
.venv\Scripts\python scripts\phase5_local.py up
.venv\Scripts\python scripts\phase5_local.py bootstrap
$env:PHASE5_DYNAMODB_LOCAL_TEST = '1'
.venv\Scripts\python -m unittest tests.test_phase5_storage -v
Remove-Item Env:PHASE5_DYNAMODB_LOCAL_TEST
.venv\Scripts\python scripts\phase5_local.py down
```

`up` starts only the pinned DynamoDB Local 2.6.1 image on loopback port 8000. `bootstrap`
creates the two local tables if missing and checks existing key schemas. `down` stops the
container/network and retains its named data volume. The opt-in test uses unique IDs, verifies
both tables' writes/reads, intersection/time queries, pagination, identical and conflicting
replays, number-limit rejection, and persistence after restarting that container. It deletes
only its own test records. Credentials are dummy local values; no AWS request is made when the
explicit loopback endpoint is set. The optional endpoint is absent in real AWS mode, which uses
the SDK credential chain. Cloud DynamoDB use and IAM remain unverified until later steps.
