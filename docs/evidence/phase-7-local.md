# Phase 7 local fault-injection evidence — passed

Date: 2026-11-12. The command run was:

```powershell
.venv\Scripts\python scripts\demo_phase7.py --report docs\evidence\phase-7-local.json
```

The final run used real loopback Kafka, SeaweedFS, DynamoDB Local and ZooKeeper, plus two
publisher processes, Analytics, Registry and Ingestion. It verified one ready leader, follower
rejection, leader termination, successor publication and old-publisher restart as a follower.
A proxy deliberately lost one successful gRPC acknowledgement; same-ID retry yielded two Kafka
records with unchanged archived content. During a ZooKeeper stop, a new request returned 503
without archive or Kafka effects. Restarting the same container with its transaction history
preserved led to fresh sessions, re-election and resumed publication.

The [machine-readable result](phase-7-local.json) for run `p7-c9202a01c505` records one Kafka
record before crash, two for the ambiguous acknowledgement, one after crash and one after session
recovery. It also records both rejected new IDs and run-time Analytics events for election, loss,
suspension and rejoin. Earlier failed runs exposed a data-reset problem and a missing Kazoo `LOST`
callback on Windows; those failures were corrected before this passing run.

The full Python suite passed: 73 tests, five opt-in integrations skipped. All eight entry-point
smoke checks passed. Temporary services stopped; local dependency containers and volumes remain.
The demo does not prove partition-safe exclusivity, zero loss or exactly-once delivery. A delayed
in-flight Kafka write remains possible after leader loss.
