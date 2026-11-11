# Phase 5 Step 4 local integration evidence — 2026-11-11

The opt-in command `.venv\Scripts\python -m unittest tests.test_phase5_consumers -v`
passed against actual local Kafka `traffic.results` and DynamoDB Local 2.6.1. Two real
API service processes joined separate consumer groups. Known results produced one
recommendation and one summary per window. Duplicate delivery kept one logical record in
each table. An invalid result was logged with Kafka location, skipped and followed by a
valid persisted result. The test stopped the DynamoDB container, produced another valid
result, observed both consumers retrying without committing, stopped their processes,
restored storage and restarted the processes with the same groups. The uncommitted result
then appeared in both tables. A changed-content replay of an existing window was logged
and quarantined; both `/readyz` endpoints returned 503, the original records remained,
and a following result was not processed. The test cleaned only its unique records and
stopped its own processes. The local DynamoDB container was subsequently stopped with
its named volume retained; the pre-existing Kafka container remained running.

The first integration attempts found two issues and were not counted as passes: the
readiness test initially raced the restarted local database, and the code checked `.err`
on a Kafka `TopicPartition` although the installed binding exposes `.error`. The test now
waits for storage recovery and checks an actual retry before killing the consumers;
the consumer verifies each synchronous commit result's `.error` field. A later test run
passed after those corrections. The normal Python suite passed 44 tests with the two
opt-in Docker tests skipped; `scripts/smoke.py` passed all eight entry points and cleanup.

Limitations: the test uses direct synthetic results on local Kafka and does not run Flink,
AWS DynamoDB, MSK, EKS, or a managed end-to-end pipeline. The quarantined conflict requires
operator intervention; no automatic overwrite/rebuild is claimed. Kafka results remain at
least once. See [reproduction steps](../phase-5-consumers.md).
