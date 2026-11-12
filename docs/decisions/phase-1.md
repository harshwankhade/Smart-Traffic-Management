# Phase 1 decision register

Review date: 2026-11-09. **Status: Phase 1 Completed with approved planning deferrals. Planned design approved; local foundation verified. No cloud deployment authorized.**

## Recorded user choices

The preceding planning conversation approved these directions:

| ID | Decision | Status |
|---|---|---|
| A1 | Evaluate AWS as the baseline provider | Approved evaluation, not an approved billable configuration |
| A2 | Six Kubernetes application services; managed-Flink Congestion Processor; Lambda Alert Service | Approved placement |
| A3 | Traffic Ingestion → Event Publisher is the service-to-service gRPC path | Approved; supersedes the brief's earlier example |
| A4 | Phase 1 local scope is health checks and contract examples, without dependency containers or business logic | Approved |
| A5 | API-first interface without custom UI | Approved |
| A6 | Budget and demonstration constraint | Originally US$5; user approved an increase to a US$8 total cap on 2026-11-12. Existing AWS account has no credits; approximately 20-minute demo. Live access/cost/quota verification deferred by user; team/deadline unconfirmed |
| A8 | User stated: "ok i have approved phase 1 decisions" | Approval recorded for P1-P7 and the presented v1 contract/domain/security choices; missing facts and unresolved protocol details are not invented |
| A10 | Bounded ZooKeeper crash-recovery demonstration, fail-closed admission and duplicate handling; no complete stale-writer fencing guarantee | User explicitly approved the recommendation with "OK APPROVED."; implement and verify only in Phase 7 |
| A9 | MSK Provisioned Standard: two kafka.t3.small brokers across two AZs; Python 3.14 APIs/Lambda; Java 17 Flink | User explicitly approved these recommendations; regional availability and Linux packaging still require verification before deployment |
| A7 | Python/FastAPI API scaffolds, Python Lambda and Java Flink; prepare remaining choices as proposals and runnable scaffold | Approved at the earlier scaffold stage; its temporary In Progress status was superseded by final design approval and verified Phase 1 closure |

The stack is now explicitly approved. Local health/smoke scaffolding is implemented and verified; the user has now approved the presented contracts and design proposals as the planned baseline. None of the domain behavior is implemented. Approval does not verify account quotas/costs or demonstrate failover. The approved bounded crash-recovery scope does not claim complete stale-writer fencing.

## Approved planned stack and infrastructure

| ID | Concrete proposal | Verification / remaining gate |
|---|---|---|
| P1 | AWS `ap-south-1` (Mumbai), one VPC, private data services | Flink regional endpoint verified publicly; account access, quotas and full regional price estimate unverified |
| P2 | **Approved:** Python/FastAPI for API health scaffolds; Python Lambda; Java 17 target for future Flink | Verified locally on Python 3.14.6/JDK 21.0.11; FastAPI 0.162.2, Uvicorn 0.54.0; Java release-17 compilation passed. Python 3.14 deployment runtime approved; Linux packaging remains unverified |
| P3 | EKS managed nodes; MSK Provisioned Standard, two kafka.t3.small brokers across two Availability Zones; RDS PostgreSQL; DynamoDB on-demand; S3; SQS Standard + DLQ; Lambda | Products and broker tier approved as planned configuration. Storage sizing, retention, IAM and networking need deployment detail; cost/access checks are user-approved assumptions, not verified facts |
| P4 | Terraform owns all cloud infrastructure and GitOps bootstrap; Argo CD owns Kubernetes workloads | No Terraform resources or Kubernetes manifests in Phase 1 |
| P5 | Dedicated three-member ZooKeeper ensemble on EKS, isolated from Kafka's internal coordination | Academic single-node local recipe may be used later, never claimed highly available |
| P6 | Prometheus/Grafana; CloudWatch Logs as common destination for K8s, Flink and Lambda; k6 for sustained load | Exporter/log shipping and HPA evidence belong to Phase 9 |
| P7 | Public HTTPS, authenticated operator access through Cognito JWT verification, ingress rate limits; internal gRPC/Kafka/ZooKeeper private; workload IAM and managed secrets | No public/admin endpoint or credential required for local scaffold |

## Approved planned v1 domain and processing rules

- Contracts live in `contracts/v1/`; schemas use JSON Schema 2020-12 and UTC RFC3339 timestamps ending in `Z`. All IDs are nonempty strings; reading IDs are generated once at the edge and reused on retries. Breaking changes require a new contract version. IDs must never be regenerated during delivery retry.
- A reading contains at least one of nonnegative integer vehicle count, nonnegative average speed in km/h, or occupancy in [0,1]. Missing measurement is distinct from zero. Sensor/intersection existence is a later service validation, not a schema-only check.
- Propose 60-second tumbling event-time windows keyed by intersection, with boundaries [start,end), 10-second bounded out-of-orderness and 30-second idle-partition detection. Finalize once the watermark passes the end; later events are counted/logged and excluded. No corrective updates in v1.
- Sum counts; average available per-reading speeds and occupancies separately (arithmetic means, not vehicle-weighted). Empty measurements remain null. These represent simulated sampling, not physical traffic estimates. Count-only windows remain `unknown` without a per-intersection capacity model.
- Congestion is `high` if mean speed <20 km/h or mean occupancy >=0.80; otherwise `medium` if mean speed <40 or occupancy >=0.50; otherwise `low` when either signal exists, else `unknown`. Count does not imply congestion by itself.
- Deduplicate stable event IDs before window aggregation; propose 24-hour state TTL and reject replay beyond that horizon unless the state is rebuilt. This is bounded deduplication, not exactly-once delivery.
- Result key is `intersection_id/window_start/window_end/v1`. Derived summaries/recommendations use deterministic upserts. High congestion proposes a simulated +10-second green adjustment; other conditions propose no adjustment. Never actuate real equipment.
- One congestion alert per high window; incident alerts on create/status change. Alert ID derives from source event/window and rule version. SQS can redeliver: Lambda writes idempotently by alert ID.
- Incident record and outbox row commit in one SQL transaction; an Incident Manager background task retries SQS emission and marks sent after acknowledgement. This is part of the existing service, not a ninth service. Implement and fault-test only in Phase 6.
- Publisher archives normalized readings to deterministic S3 event keys and publishes Kafka records with stable event IDs. Retry both operations after ambiguous acknowledgement; acknowledgement requires both. Partial archives/publications remain possible and must be documented and tested in Phase 3.

## ZooKeeper decision: bounded crash recovery approved

The user selected the bounded crash-recovery design described below. This supersedes the earlier unresolved choice between complete transactional fencing and a limited demonstration. Full stale-writer fencing is not part of the approved guarantee; shared transactional IDs alone are not claimed sufficient. Phase 7 must implement the approved recipe, routing/retry behavior and failure tests, and record limitations. No election code or failover proof exists in Phase 1.

## Public feasibility and cost evidence

Checked 2026-11-09 using official public documentation; no AWS account queries were performed.

- [Flink endpoints and quotas](https://docs.aws.amazon.com/general/latest/gr/ka.html): Mumbai and N. Virginia listed. Public quotas are not proof of account entitlements.
- [Managed Flink 2.2 compatibility](https://docs.aws.amazon.com/managed-flink/latest/java/flink-2-2.html): Java 17 supported; do not infer deployed runtime compatibility from local JDK 21.
- [Kafka output support](https://docs.aws.amazon.com/managed-flink/latest/java/how-sinks.html): managed Flink supports Kafka/MSK sinks. Future source/connector/authentication pairing still needs integration verification.
- [EKS pricing](https://aws.amazon.com/eks/pricing/): standard-support control plane $0.10/cluster-hour, excluding workers and networking.
- [MSK pricing](https://aws.amazon.com/msk/pricing/): the US East Serverless example charges $0.75/cluster-hour plus partitions, traffic and storage. It is not a zero-idle-cost service.
- [Flink pricing](https://aws.amazon.com/managed-service-apache-flink/pricing/): N. Virginia example $0.11/KPU-hour plus storage; each running application has an additional orchestration KPU charge.

Illustrative US East subtotal for 24 hours: EKS control plane $2.40 + MSK Serverless cluster $18 + Flink one processing KPU and one orchestration KPU $5.28 = **$25.68**, before workers, broker partitions/storage, Flink storage, SQL, networking/NAT, load balancers, logs, traffic and tax. At 730 hours this partial subtotal is $781.10. This is a pricing-risk illustration, **not a Mumbai quote, complete estimate, budget or provisioning approval**. Prepare a regional calculator estimate with actual sizes and active hours before choosing the MSK tier.

## Phase gates

### Approved and verified local scaffold (P2)

Six independent health-only FastAPI modules expose `GET /healthz`, returning the service name, `status: ok`, and `scope: scaffold`. They bind to `127.0.0.1`; default ports are 8001 Sensor Registry, 8002 Traffic Ingestion, 8003 Event Publisher, 8005 Signal Recommendation, 8006 Incident Manager and 8008 Traffic Analytics. API documentation is disabled. Publisher HTTP health is auxiliary, not implementation of the proposed gRPC service.

A local-only Python Lambda smoke invocation and Java `--smoke` entry point are implemented. Neither processes events or loads Flink. `scripts/smoke.py` passed checks for all six processes on ephemeral loopback ports, exact health responses, unknown/business route rejection and both non-HTTP entry points. Java bytecode version 61 confirms the release-17 target; execution used JDK 21. The script stops its children. Dependencies are pinned in `requirements-lock.txt`; no dependency containers or cloud SDKs were added.

1. P1-P7, v1 contracts/rules, MSK tier, Python runtime and the bounded ZooKeeper crash-recovery scope are approved. No Phase 1 technical approval gate remains open.
2. Cloud affordability and AWS access/quotas are **approved as assumptions for planning**, per the user. Defer live verification until before cloud provisioning; these checks no longer block local planning. The US$5 cap, no-credit assumption and approximately 20-minute demo remain unchanged. No cloud deployment is authorized.
3. Local checks passed: 10 unit/schema tests, all eight scaffold entry points and `pip check`. Managed-runtime, protobuf and AWS account checks are unverified.
4. Confirm team size/deadline later; never invent member names or create a false final `task_divison.txt`.
5. Phase 2 remains Not Started and requires separate user authorization.

## Closure evidence and deferred checks

Phase 1 is **Completed with approved planning deferrals**: mandatory technical directions are approved and the local acceptance checks passed. Cloud cost/access/quota checks are explicitly accepted by the user as assumptions for planning, not verified results. Team allocation and deadline are deferred until real details are provided; never invent the required member/task file. Linux packaging, managed-runtime behavior, protobuf interoperability and cloud integration remain future verification work. No billable deployment or Phase 2 implementation is authorized by this closure.

## Binding budget update

Runtime update: the user estimates approximately **20 minutes total application/demo runtime**. Treat this as a planning estimate, not a verified full billable lifecycle or guaranteed maximum. Cost estimates must additionally account for provisioning, readiness, rehearsal if needed, teardown, service billing minimums and residual resources. The US$5 cap and zero-credit assumption remain unchanged. A 20-minute demonstration alone is not evidence that deployment fits the cap.

Account update: the user confirms an existing AWS account with **no credits**. This is user-provided information, not a live verification of login, plan, permissions or quotas. Assume no credit offset in cost estimates. The total out-of-pocket ceiling remains **US$5**. Account plan, local authentication, regional permissions, quotas and the full deployment lifecycle cost remain unverified. Do not create resources merely to test eligibility or affordability.

The user wants minimum expenditure and cloud use only long enough for a teacher demonstration, with a maximum project spend of **US$5**. Treat this conservatively as a total spending ceiling, not US$5 per day or per service. Do not assume credits are available or additional out-of-pocket spending is allowed. Develop/test locally; provision nothing until an estimate includes setup, rehearsal, demonstration, teardown, residual storage, networking and applicable taxes within the cap. The earlier AWS baseline is not evidence of affordability. Credits or a college lab account may make the required managed-cloud demonstration feasible; a local-only demonstration requires the teacher's acceptance because it does not satisfy the documented managed-cloud requirements.

## User-approved planning assumptions

The user explicitly instructed: "for now consider Cloud affordability and AWS access and quotas as approved." Record both gates as **approved for planning, verification deferred**. No claim is made that a US$5 deployment has been costed or that AWS authentication, IAM permissions or regional quota headroom have been tested. This overrides treating those unverified checks as blockers to local planning; it does not raise the spending cap, authorize resource creation, authorize Phase 2 implementation. Subsequent approvals separately settled the Kafka tier, Python runtime and bounded ZooKeeper scope.

## Approved ZooKeeper design: bounded crash recovery

Approved academic demonstration scope: ephemeral-sequential publisher election with predecessor watches; only a connected elected publisher is ready; stop accepting new work immediately on connection suspension/loss and require fresh election after session expiry. Use stable event IDs, bounded retries, idempotent Kafka production where supported and downstream event-ID deduplication. Prefer temporary unavailability to intentionally accepting writes under uncertain leadership.

Demonstrate a confirmed publisher process crash, successor election and restored publication; also test ZooKeeper disconnection/session expiry, ambiguous acknowledgements, same-ID retry and restart of the old process. A restarted process rejoins election with a fresh session and must not restore a cached leader role. Ingestion discovers/retries the active publisher; clients preserve IDs and receive transient unavailability until takeover completes.

Scope limitation: readiness and session callbacks cannot fence an in-flight or paused Kafka producer. Deduplication mitigates repeats but does not prove exclusive publishing. Network partitions/process pauses may cause stale in-flight writes; no partition-safe split-brain protection, zero-loss or end-to-end exactly-once claim is made. The acceptance evidence must distinguish a connected leader accepting new requests from broker acceptance of delayed old requests. A stronger fenced design remains a separate design change if required by the evaluator. Do not rely on a shared transactional ID alone as a complete fencing protocol.

**Approved by the user.** This selects the limited failure-demonstration option and supersedes requiring a complete custom transactional initialization protocol for this academic scope. It does not implement Phase 7 or authorize it.
