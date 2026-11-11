# Phase 4 - Completed (11 November 2026)

Implemented Java 17 Flink minute windows from `traffic.raw` to `traffic.results`, with stable
window IDs, bounded deduplication, approved congestion rules, late-data exclusion and checkpoints.
The local Flink 2.2 build remains available; a separate Flink 1.20 build targets Amazon EMR
7.14 on EC2. The Kafka result sink remains at least once.

Local preflight ran both Maven profiles (`mvn -f services/congestion-processor/pom.xml package`
and `-P emr package`): seven Java tests passed per profile. The Python suite passed 36 tests.
The local Kafka/Flink demo passed known-window, duplicate, late-reading and checkpoint recovery
checks. Terraform format, validation and seven mocked tests passed. Results are in
[`phase-4-step-3.json`](../evidence/phase-4-step-3.json).

The user authorized temporary Mumbai deployment and teardown. Run
`stp4-91dd0a43a8` began from a reviewed 63-create Terraform plan. After a requested pause
during MSK creation, the exact active cluster was imported into partial state; the resumed
plan had seven creates, one JAR update and no deletes. `scripts/run_phase4_cloud.py` launched
EMR and both verification steps completed. Stage 1 consumed raw Kafka input and observed a
two-reading medium window (count sum 5, speed 20, occupancy 0.6). Stage 2 restored S3
checkpoint 1 and observed the pending three-reading low window (speed 40) without counting
the retried ID again. Actual Kafka-derived records matched the approved result schema.

The runner terminated EMR, emptied only the run-owned versioned bucket and destroyed the
stack. `scripts/audit_phase4_cleanup.py --remove-new-service-role` found no run-owned
resources; Terraform state is empty and deployment approval is false. See
[`managed evidence`](../evidence/phase-4-cloud.json) and
[`cleanup audit`](../evidence/phase-4-cleanup.json). The written estimate was waived; actual
billed cost against US$5 was not checked. No full cloud system was deployed. Phase 5 remains
Not Started.
