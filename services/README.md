# Eight application service boundaries

Sensor Registry and Incident Manager implement Phase 2 REST workflows with separate local SQL persistence. Traffic Ingestion and Event Publisher implement Phase 3 REST/gRPC publication and archival. Congestion Processor implements Phase 4's real local Flink job, separate Kafka results and checkpoint restoration; three other entry points retain Phase 1 health/smoke behavior. See `catalog.json` for placement, root README for setup and `scripts/demo_phase4.py` for processing evidence. Managed Flink, alert delivery, election and live AWS integration remain unverified or unimplemented.

Each prescribed service has its own directory. Supporting scripts, brokers, databases, ingress and monitoring do not count as additional application microservices.
