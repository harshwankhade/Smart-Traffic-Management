# Phase 9 observability, scaling and cloud preflight design

**Status: Step 1 planning and read-only preflight complete; cloud run blocked by the cost gate.** This document prepares Phase 9 only. It does not approve an apply, a Kubernetes deployment, a public HTTPS request, a commit or a push.

## Capacity and lifecycle envelope

The approved EC2 quota is 16 vCPUs. The Phase 9 plan deliberately uses 12: four EKS `t3.large` workers (8 vCPUs) and one single-node EMR `m5.xlarge` (4 vCPUs). The remaining four vCPUs are recovery headroom and must remain unallocated. The Terraform root currently has two `t3.large` workers and one `m5.xlarge`; Step 2 must make the EKS desired/minimum size four without changing the EMR shape.

`t3.large` instances are burstable. The load run must record CPU credit balance and surplus-credit charges alongside node CPU; stop or reduce the test if the credit trend makes the result or cost unrepresentative.

Provisioning may run for at most 90 minutes. Begin teardown no later than three hours after the apply starts, then allow up to two hours for deletion and independent audit. The EMR idle timer is not a teardown mechanism. A fresh estimate must include the four EKS nodes, EMR, MSK, NAT, RDS, ALB, EBS, logs, data transfer, public IPv4 and monitoring storage. It must show that known project spend plus the proposed run remains within the approved US$25 cap.

## Observability design

Prometheus and Grafana run in EKS as GitOps-managed monitoring workloads. Prometheus scrapes Kubernetes, node and kube-state metrics plus a `/metrics` endpoint on each of the six Kubernetes application services. Grafana has Prometheus and CloudWatch data sources: Prometheus supplies request rate, error rate, latency and cluster health, while CloudWatch supplies Lambda and EMR service metrics.

Step 2 will add lightweight request instrumentation to the six Python services. It will emit request count, response-status count and latency histograms with bounded labels; it will not label metrics with event IDs, sensor IDs, intersection IDs or request bodies. The Flink job's existing counters and checkpoints remain the processor metrics; the dashboard will pair them with EMR/CloudWatch status rather than introduce a second processor service. Lambda invocation/error/duration metrics come from CloudWatch.

CloudWatch Logs is the single log store. An EKS log collector sends container stdout/stderr and cluster control-plane logs to run-scoped groups. Lambda already writes there. EMR requires a Terraform-managed bootstrap/configuration that forwards Flink/YARN container logs to the same retention-governed service; its existing S3 log/checkpoint path remains separate storage, not the central log proof. Logs retain 7 days, use the run ID and service/runtime name as searchable fields, and must never contain request bodies or secrets.

## Scaling and load design

The two HPA targets are Traffic Ingestion and Traffic Analytics. Both stay GitOps-managed and use CPU utilization from declared CPU requests. Traffic Ingestion has a minimum of two and maximum of four replicas to preserve its existing availability posture; Traffic Analytics has a minimum of one and maximum of four. Step 2 must set resource requests so the combined HPA maxima, ZooKeeper, Event Publisher, fixed services and monitoring stack can schedule on four workers. It must prove this with rendered manifests and a capacity calculation before any run.

k6 will be a one-shot, run-scoped load generator outside the application workloads. It will use unique synthetic IDs, send sustained valid reading traffic to Traffic Ingestion, and issue scoped read traffic to Traffic Analytics. The test plan uses a warm-up, a sustained stage long enough for two HPA sampling/scale decisions, and a cool-down. It records offered/observed RPS, error rate, latency percentiles, replicas and node CPU before/during/after. The acceptance run must confirm both end-to-end workflows after scale-out. No performance SLA is implied.

## Required dashboards and evidence

1. **Application dashboard:** per-service RPS, 4xx/5xx rate and p50/p95 latency for the six Kubernetes services.
2. **Cluster dashboard:** node/pod CPU and memory, pod readiness/restarts, requested versus allocatable resources, HPA desired/current replicas and T3 CPU credits.
3. **Pipeline dashboard:** Kafka/consumer or service health, Flink checkpoint/counter status, Lambda invocation/error/duration, and EMR state.
4. **Log queries:** one correlation path for reading-to-result-to-recommendation and one for incident-to-alert, plus a publisher failover query. Evidence must cover all eight runtimes.

## Current preflight result and gates

Read-only checks on 2026-11-16 using `smarttraffic-sdk` identified account `520646131316` in `ap-south-1`. The Standard On-Demand EC2 vCPU quota is **16**, confirming the planned 12-vCPU layout and four-vCPU reserve. A `Project=smarttraffic` tagged-resource inventory returned no resources, and `terraform -chdir=infrastructure/terraform/phase8 state list` returned no tracked runtime resources.

Cost Explorer reported **US$14.8184460716** estimated account-wide unblended usage for 1–16 November. Against the US$25 project cap, **US$10.1815539284** remains if that account-wide figure is treated conservatively. That amount is not project-attributable and can lag.

### Dated five-hour lifecycle estimate

The estimate uses on-demand Mumbai prices retrieved on 2026-11-16, the maximum three-hour runtime before teardown, and two teardown/audit hours. The fixed hourly subtotal is **US$0.9155**: four `t3.large` workers (4 × US$0.0896 = US$0.3584), one `m5.xlarge` (US$0.202), EMR charge (US$0.048), two `kafka.t3.small` brokers (2 × US$0.0491 = US$0.0982), EKS control plane (US$0.10), NAT gateway (US$0.056), RDS `db.t4g.micro` (US$0.021), and ALB plus one small LCU (US$0.0319). Five hours of this baseline is **US$4.5775**.

Add US$0.20 for short-lived EBS/MSK storage, US$0.70 for modest logs, NAT processing, S3/SQS/Lambda/DynamoDB, and public IPv4 usage, and a 25% lifecycle contingency (US$1.3694). This gives a **US$6.85 planning estimate**. The HPA test runs on burstable T3 workers; if it spends CPU credits at the full 5.6 vCPUs above the four-node baseline for five hours, it can add approximately **US$1.40**. The prudent range is therefore **US$6.85–US$8.25**, before tax and late-posting charges.

The US$6.85–US$8.25 range fits within the conservative US$10.1815539284 remaining amount, leaving at least **US$1.93** before tax and delayed charges. This passes the planning cost gate, but it does not authorize a run. Before any separate cloud-run approval, rerun Cost Explorer and the reviewed-plan check; stop if the fresh remaining amount is less than the high estimate plus a US$1.50 reserve. The separate DNS zone and ACM certificate may remain, but all runtime resources must be run-scoped and audited after teardown.

The strict public HTTPS request is the first acceptance action after the runtime is healthy and before load work or teardown. It requires the user to change to an independent trusted network and give a separate explicit approval immediately before that request. Normal certificate validation must remain enabled; `--insecure` or equivalent is forbidden. A failed or unavailable check blocks Phase 8 closure and must be recorded before proceeding with Phase 9 evidence.

## Step 2 preparation result

The reviewed artifacts are in `docs/phase-9-observability.md`: bounded HTTP metrics in the six Kubernetes services, GitOps-managed Prometheus/Grafana, Metrics Server, Fluent Bit, two HPAs and Grafana panels, Terraform-owned CloudWatch roles/log groups and EMR bootstrap logging, and a unique-ID k6 script. GitOps rendering, the focused metrics test and Terraform validation passed. These results are static preparation only; no Kubernetes or AWS runtime was deployed.
