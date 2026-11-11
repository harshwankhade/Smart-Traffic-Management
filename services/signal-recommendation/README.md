# signal-recommendation

Phase 5 Step 2 adds pure rules in `recommendation/rules.py`. `recommend(result)`
validates a Phase 4 window and returns a deterministic, simulation-only recommendation.
High congestion suggests 10 additional green seconds; other levels suggest zero.
Kafka, DynamoDB and query APIs belong to later steps. The HTTP entry point still exposes
only the original health scaffold. See `docs/decisions/phase-5.md` for the approved design.

Approved placement: Kubernetes. See the root README for run and smoke-test commands.
