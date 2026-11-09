# Eight application service boundaries

Sensor Registry and Incident Manager now implement Phase 2 REST workflows with separate local SQL persistence. The other six service entry points retain Phase 1 health/smoke behavior. See `catalog.json` for approved placement, the root README for setup, and `scripts/smoke.py` plus `scripts/demo_phase2.py` for verification. No stream job, alert delivery, election logic or cloud integration is implemented.

Each prescribed service has its own directory. Supporting scripts, brokers, databases, ingress and monitoring do not count as additional application microservices.
