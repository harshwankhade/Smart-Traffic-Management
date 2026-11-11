# Phase 4 local verification - 2026-11-10

Scope: real local Kafka/Flink containers, not managed AWS operation.
Authoritative input/output and checkpoint metadata: [JSON evidence](phase-4-verification.json).

## Commands and outcomes

- Maven 3.9.11 `package`, Java release 17: **four tests passed**. Two execute actual Flink
  MiniCluster jobs; coverage includes boundary assignment, multiple intersections, duplicates,
  conflicting IDs, explicit watermarks/late exclusion, thresholds, missing values, zeros,
  sub-nanosecond timestamp fractions and count sums above signed 64-bit range.
- `.venv\Scripts\python scripts\phase4_local.py up`: started Flink 2.2.0 Java 17 managers,
  preserved Phase 3 Kafka/SeaweedFS volumes, verified both local topic configurations.
- `.venv\Scripts\python scripts\demo_phase4.py --report docs/evidence/phase-4-verification.json`:
  **passed**, final prefix `p4-30924be466`. Produced eleven synthetic input records including
  duplicates and a deliberately late reading; four distinct window results were retrieved
  from actual `traffic.results`. Zero duplicate result records occurred in this observed run;
  duplicates remain permitted by the at-least-once guarantee.
- Retained checkpoint 2 restored explicitly after canceling the owned job and restarting both
  Flink containers. REST checkpoint metadata confirmed restoration. Pending aggregate state
  and deduplication state survived; retries did not inflate the reopened pending window.
- Existing Python suite: **31 passed**; `pip check`: no broken requirements.
- `scripts\smoke.py`: all eight liveness entry points passed, with child process cleanup.
- `scripts\demo_phase2.py`: HTTP workflows, outage handling and actual restart durability passed.
- `scripts\demo_phase3.py --failure-tests --report .data/phase4-phase3-regression.json`:
  passed after the listener change, with eight logical archived events, fourteen Kafka records,
  six duplicate deliveries, dependency outages and container-restart persistence.
- Terraform Phase 2/3/4 formatting, validation and mocked-provider tests were run separately;
  all three roots passed validation and two mocked tests each (six total). No AWS-backed
  plan/apply was run.

## Known inputs and results

| Window | Input excluding retries/late data | Actual result |
|---|---|---|
| main 10:10-10:11 UTC | counts 2+3, speeds 10+30, occupancy 0.4+0.8 | 2 readings, count 5, speed 20, occupancy 0.6, medium |
| other 10:10-10:11 UTC | count 7 only | 1 reading, count 7, null means, unknown |
| main 10:11-10:12 UTC | speed 45 before restart +35 after restart | 2 readings, null count, speed 40, null occupancy, low |
| watermark 10:11-10:12 UTC | count 0 synthetic advancing input | 1 reading, count 0, null means, unknown |

## Failures corrected and limits

Initial compile exposed removed Flink configuration APIs and a missing connector-base dependency;
both were corrected. Initial execution exposed transitive Jackson version mismatch, fixed using a
matching BOM. A deterministic watermark test captured the nonserializable test instance; it now
uses a static generator. One recovery demo asserted a REST counter before the metrics cache
refreshed; bounded polling now waits for the observed counter. Final tests and real demo passed.

Non-failing SLF4J test-binding and JRE module warnings remain. A 24-hour TTL soak, abrupt-kill
recovery, real managed Flink, IAM/TLS networking, cloud snapshots and regional lifecycle cost are
not claimed tested. No AWS profile or usable credentials was found in the current session.
