# incident-manager

Phase 2 REST API implemented with service-owned SQLAlchemy models and persistent local SQLite. See [API contracts](../../docs/phase-2-api.md), [decisions](../../docs/decisions/phase-2.md) and the [root README](../../README.md) for setup.

Run from project root: `.venv\Scripts\python scripts\run_service.py incident-manager`. Run the restart/failure demo with `scripts/demo_phase2.py`. Health payload remains compatible with Phase 1; `/docs` and `/openapi.json` are available locally. RDS PostgreSQL configuration is prepared but unapplied and unverified. Incident create/status changes atomically stage alert requests in the service-owned SQL outbox. Set `PHASE6_ALERTS_ENABLED=1` and `ALERT_QUEUE_URL` to enable its background SQS sender. Without these settings, requests remain pending for later delivery. No Alert Service or cloud resources are deployed in Step 2.
