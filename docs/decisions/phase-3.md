# Phase 3 approved decisions and delivery contract

The user authorized the Phase 3 implementation plan, including real local Docker Kafka/SeaweedFS, real gRPC, persistent archival and unapplied MSK/S3 Terraform. No cloud creation or Phase 4 is authorized. The US$5 total cloud cap, no credits and deferred live affordability/access/quota checks remain binding.

## Implemented local interfaces

- Ingestion exposes `POST /readings`, `/docs`, `/openapi.json`, existing `/healthz` and dependency `/readyz`. Client event IDs, sensor/intersection IDs and UTC observation timestamps are preserved. Registry must confirm an active sensor and matching intersection through a single REST GET with two-second operation timeouts.
- `contracts/v1/publisher.proto` is implemented by an actual gRPC server in the Publisher service process. `scripts/generate_proto.py` reproducibly generates the package-relative Python stubs using pinned tools. Optional measurement presence is preserved, including explicit zero.
- Shared wire validation is in `contracts/python/traffic_contracts/reading.py`, not a ninth service or shared domain monolith. IDs are nonblank and <=128 characters. Counts are integers in [0, 2^63-1]. Measurements must be finite, correctly typed and nonnegative; occupancy <=1. At least one measurement is required; explicit nulls are rejected. UTC timestamps require seconds and `Z`; canonical fractional seconds have at least six digits, trim redundant trailing zeros and preserve additional precision. No age/future-time policy is imposed in Phase 3.
- Publisher revalidates RPC input and serializes all attempts within one active process. No ZooKeeper, distributed lock or multi-writer guarantee exists. Internal local gRPC uses loopback plaintext, not a claimed cloud transport-security implementation.

## Archive then Kafka

The archive key is `normalized/v1/<sha256(event_id)>.json`; bytes are sorted-key UTF-8 JSON with stable number/timestamp formatting. Read existing bytes before writing. Identical bytes permit retry; different bytes produce a conflict without another Kafka write. This read/compare/write sequence is protected by the single-process publication lock, not an atomic cross-process S3 transaction. Do not run overlapping publisher replicas before the later coordination design.

Archive persistence precedes Kafka publication. Kafka uses `traffic.raw`, intersection ID as key, idempotent producer mode, `acks=all` and a ten-second delivery timeout. Publication is accepted only after archive success and Kafka's successful delivery callback. Ingestion's gRPC deadline is 15 seconds without automatic application retry; queued RPCs honor cancellation before new side effects. An operation already in progress can finish after its caller times out.

Same ID/content can create multiple Kafka records, especially after lost acknowledgements and restarts. The archive remains one logical payload. Archive-only partial outcomes are expected when Kafka fails. There is no cross-system atomicity or end-to-end exactly-once promise; later consumers must deduplicate stable IDs. A changed payload for an already archived ID is rejected even if the first attempt never reached Kafka.

HTTP success is 202 `{event_id, accepted: true}`. Input/reference failures are 422; conflicts 409; temporary Registry/gRPC/archive/Kafka failures and RPC deadlines 503; unexpected failures 500. Application errors contain `detail` and the event ID when available. gRPC codes are INVALID_ARGUMENT, ALREADY_EXISTS, UNAVAILABLE and INTERNAL respectively. Readiness checks Registry, gRPC transport and the Publisher's archive/Kafka readiness endpoint; liveness retains the Phase 1 response and is not delivery evidence.

## Infrastructure boundary

Docker Compose pins Apache Kafka 3.9.1 and SeaweedFS 4.42. Both bind host ports only to loopback and retain data in named volumes. Local Kafka runs as root inside its container because the Docker Desktop named volume was initially unwritable by the image user; this is a local-demo configuration, not a cloud deployment security claim. Configure generates ignored local-only credentials and never prints them. A local topic/bucket bootstrap is explicit. Kafka auto-topic creation is disabled; `traffic.raw` has one partition, RF=1 and 24-hour deletion retention. No ZooKeeper container is used in this phase.

AWS provider 6.45.0 is pinned. Phase 3 Terraform consumes Phase 2 VPC/subnet/application-group/route-table outputs, adds private IAM/TLS MSK Standard with two kafka.t3.small brokers (3.9.x, 10 GiB each), RF=2/minISR=2 topic, and private encrypted versioned S3. Security-group rules and an S3 gateway endpoint extend the existing isolated network; no duplicate VPC or RDS is created. Publisher, verifier and topic-admin policies are separate and unattached until deployment. Publisher/verifier bucket listing is bucket-scoped to support readiness and missing-key checks; object access is restricted to the archive prefix, with no delete permission. TLS-only S3 policy and non-forced bucket deletion are retained. Workload-role attachment, IAM/network compatibility and actual costs remain unverified. A broker outage can stop cloud writes with minISR=2.

Validation and mocked plan tests do not authorize or execute a real AWS-backed plan/apply. Full MSK/S3 cloud proof remains deferred.
