# Phase 3 observed local integration evidence

Verification date: 2026-11-09. This is local evidence, not a claim of MSK/AWS S3 operation.

Command: `.venv\Scripts\python scripts\demo_phase3.py --failure-tests`

The completed run reported:

```json
{
  "run_prefix": "run-22ab87e92c6f",
  "logical_events": 7,
  "kafka_records": 13,
  "duplicate_records": 6,
  "rejected_without_side_effects": 4
}
```

The command consumed actual Apache Kafka 3.9.1 records from `traffic.raw` and retrieved matching archived JSON through SeaweedFS 4.42 S3. It checked HTTP -> gRPC, archive/Kafka acknowledgement, negative/unknown/mismatched/inactive rejection, duplicate conflict, concurrent identical attempts, Publisher restart, deliberately lost successful response, Registry/Publisher outages, archive outage, Kafka outage after archival, same-ID recovery and container-restart persistence. Its service processes were stopped; Compose dependency containers and volumes were retained.

Kafka connection-error logs during intentionally stopped/restarting brokers were expected; final verification passed. Initial Kafka startup failed because its image user could not write the Docker-created volume. The local configuration was corrected without deleting data, then bootstrapping and integration passed.

## Final expanded acceptance run

The latest successful run added real concurrent changed-content attempts and saved its exact summary in [phase-3-verification.json](phase-3-verification.json): eight logical events, fourteen Kafka records, six duplicates, four rejected readings with no side effects, and one accepted/two conflicting concurrent variants. The command completed process cleanup successfully. Independent `inspect_phase3.py archive` and `consume` commands retrieved the first accepted event and observed its two expected Kafka deliveries at offsets 13 and 14. Local bootstrap also verified the actual topic partition/replica count and retention/minISR settings.
