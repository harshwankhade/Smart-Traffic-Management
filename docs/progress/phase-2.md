# Phase 2 - Completed (local services and unapplied IaC)

Phase 2 implements Sensor Registry and Incident Manager using the user-approved local SQLAlchemy/SQLite approach. The approved boundary includes prepared private RDS Terraform without provisioning; cloud behavior is not claimed complete. Phase 3 remains Not Started.

Registry now creates, retrieves and updates intersections/sensors, validates references and enforces immutable identities. Incident Manager creates records after a two-second-timeout Registry REST lookup, generates UUID revision IDs/UTC timestamps, and supports description updates and terminal resolution. No-op updates preserve metadata; conflicting writes return 409. Separate models, databases and PostgreSQL schema/role definitions preserve ownership. No alerts, outbox, Kafka, Flink or ZooKeeper behavior was added.

Important files include the two service packages, `tests/test_phase2.py`, `scripts/demo_phase2.py`, `docs/phase-2-api.md` and `infrastructure/terraform/phase2/`. README, architecture, configuration, versioned contracts, dependency pins and the smoke runner were updated. PostgreSQL bootstrap/initial SQL is prepared but unexecuted.

Verification passed: `.venv\Scripts\python -m unittest discover -s tests -v` (21 tests), `scripts\smoke.py` (all eight entry points), `scripts\demo_phase2.py` (real HTTP CRUD, Registry outage without partial persistence, actual process restarts), and `-m pip check`. Terraform `fmt -check -recursive`, `validate`, and two mock-provider plan tests passed; no AWS-backed plan or apply ran. Initial dependency/provider downloads required network approval. A computed-route assertion initially failed, then passed after explicitly declaring no routes.

Limitations: live PostgreSQL roles/SQL, IAM authentication, Linux packaging, region availability, costs and cloud connectivity remain unverified. Starlette emits a non-failing HTTPX TestClient deprecation warning. Terraform retains deletion protection/backups/final-snapshot safeguards requiring future cost/teardown review. The US$5 cap remains binding. Next: review Phase 2 results and separately authorize Phase 3.
