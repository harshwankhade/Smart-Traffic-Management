# event-publisher

Implemented Phase 3 service. See [API/delivery contract](../../docs/phase-3-api.md), [decisions](../../docs/decisions/phase-3.md), and [root setup](../../README.md).

Run from root using `.venv\Scripts\python scripts\run_service.py event-publisher --phase3-local` after configuring/starting/bootstrap of local infrastructure. Publisher runs one process with HTTP health plus actual gRPC. Ingestion validates Registry references before calling gRPC.

Use `scripts/demo_phase3.py --failure-tests` to verify actual local Kafka records and archive objects. AWS deployment remains unverified and unauthorized; ZooKeeper, Flink, alerts and HPA are not implemented here.
