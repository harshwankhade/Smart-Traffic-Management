# Phase 7 — promptable steps

Work through these steps in order. Each prompt authorizes **only that step**; stop after reporting its changes and verification. Follow the bounded crash-recovery scope in `docs/decisions/phase-1.md` and the Phase 7 acceptance criteria in `ROADMAP.md`. Preserve ordinary single-publisher startup. Phase 8 cloud integration, GitOps and HPA work are outside this plan.

## 1. Coordinate two publishers

**Prompt:** “Do Phase 7 step 1 only.”

Add an opt-in local ZooKeeper setup and ephemeral-sequential election with predecessor watches for at least two Event Publisher instances. Expose leader identity and readiness; reject new publication when not elected or when ZooKeeper is suspended/lost, and re-elect with a fresh session after expiry or restart. Keep the current single-publisher path working. Add focused election/readiness tests and document how to start both replicas.

## 2. Route and retry ingestion safely

**Prompt:** “Do Phase 7 step 2 only.”

Make Traffic Ingestion discover the active publisher and retry transient leader changes with the **same event ID** and a bounded retry policy. Ensure the publisher rechecks its role before accepting new work, retains existing archive/Kafka acknowledgement behavior, and handles ambiguous acknowledgements and same-ID retries without claiming exactly-once delivery. Test leader loss, fail-closed admission, retries and old-process restart.

## 3. Record recovery in Traffic Analytics

**Prompt:** “Do Phase 7 step 3 only.”

Define a small, versioned recovery-event contract and add publisher leadership/failure/recovery logs and measurements. Persist and expose these events through Traffic Analytics using its existing ownership and query conventions. Test event identity, replay, query behavior and failure handling. Do not add a ninth service or a general monitoring stack.

## 4. Prove failover and close the phase

**Prompt:** “Do Phase 7 step 4 only.”

Create and run a repeatable local fault-injection demo with real ZooKeeper, two publishers and Kafka: establish one leader, crash it, observe successor election and resumed publishing, then check stable IDs, Kafka output and analytics recovery records. Also exercise ZooKeeper disconnect/session expiry, ambiguous acknowledgement and old-leader restart; distinguish rejected **new requests** from potentially delayed **in-flight Kafka writes**. Record commands/results and limitations in `docs/evidence/` and `docs/progress/phase-7.md`, update the relevant README/architecture/roadmap status only to the extent evidence supports, and stop. Do not claim partition-safe exclusivity, zero loss or end-to-end exactly-once behavior.
