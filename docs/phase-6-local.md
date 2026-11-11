# Phase 6 Alert Service local demo

From the project root, the self-contained demo needs only installed Python dependencies:

```powershell
.venv\Scripts\python scripts\demo_phase6_alerts.py
```

It exercises the real Signal Recommendation callback and incident SQL outbox, transfers their requests through an in-memory SQS stand-in, runs the actual Alert Service batch handler, and checks two logical outcomes after duplicate delivery. It uses a temporary SQLite database and memory-backed alert table. This mode does **not** prove SQS, DynamoDB, or Lambda integration.

For a real local DynamoDB table, start Docker Desktop and run:

```powershell
.venv\Scripts\python scripts\phase6_local.py up
.venv\Scripts\python scripts\phase6_local.py bootstrap
.venv\Scripts\python scripts\demo_phase6_alerts.py --dynamodb-local
.venv\Scripts\python scripts\phase6_local.py down
```

The opt-in mode uses the existing loopback DynamoDB Local container. It creates/verifies `traffic_alerts` with an `alert_id` partition key, uses unique demo IDs and removes its own alert records. The Docker volume is retained. Queue delivery remains simulated; real SQS/Lambda is reserved for the separately authorized cloud step.

Both modes passed on 2026-11-11. Each processed three simulated queue messages (one duplicate congestion delivery) into two logical alerts with zero replay failures. The DynamoDB Local table was created and verified, then the run-owned container/network were stopped and removed; its volume was retained. Docker Compose required execution outside the workspace sandbox because the sandboxed process could not access the Docker configuration and engine pipe. No AWS calls were made.
