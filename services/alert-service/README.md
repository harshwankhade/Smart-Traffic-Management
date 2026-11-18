# alert-service

Approved placement: serverless. Phase 6 Step 3 implements the SQS batch handler and owned DynamoDB alert table repository. The function validates each request, conditionally inserts the recorded outcome, treats identical replay as success and reports malformed, conflicting or transiently failed records through `batchItemFailures`. Set `ALERTS_TABLE` for the owner table; `DYNAMODB_ENDPOINT_URL=http://127.0.0.1:8000` selects DynamoDB Local. The deployed Lambda package must include `alerts.py`, `handler.py`, `traffic_contracts`, and Boto3 dependencies.

The Phase 1 `--smoke` entry point remains. See [the local demo](../../docs/phase-6-local.md). Cloud queue/function provisioning and invocation remain Step 4/5.
