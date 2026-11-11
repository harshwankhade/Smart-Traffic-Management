# traffic-analytics

Phase 5 Step 2 adds the `contracts/v1/summary.schema.json` record contract for
persisting Phase 4 results. The HTTP entry point is still a health-only scaffold;
Kafka, DynamoDB and query APIs belong to later Phase 5 steps. See
`docs/decisions/phase-5.md` for the approved design.

Approved placement: Kubernetes. See the root README for run and smoke-test commands.
