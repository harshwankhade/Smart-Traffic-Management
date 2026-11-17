# Phase 9 Step 3 runtime evidence — 2026-11-16

## Strict independent-client HTTPS gate

After the user confirmed use of a mobile hotspot and separately approved the check, a normal certificate-validating `curl.exe` request was made to the public endpoint. No insecure/TLS-bypass option was used.

`POST https://api.smarttrafficmgmt.online/intersections` returned HTTP `201` for the synthetic `phase9-https-20261116` record. curl reported `TLS_VERIFY:0` and connected to the public ALB IP `3.6.193.177`. This closes the carried-forward certificate-validation gap; the earlier `/healthz` 404 and malformed-payload 422 attempts also had `TLS_VERIFY:0`, but are not counted as the successful API proof.

## HPA and in-cluster sustained-load observation

The `phase9-k6-7lqz4` Job used the pinned `grafana/k6:0.54.0` image and internal Kubernetes service DNS, avoiding local port-forward failure. Its profile peaked at 200 virtual users (160 ingestion plus 40 analytics). During the run, both CPU HPAs scaled to their configured maximum of four replicas: Traffic Analytics reached 99--296% CPU against its 30% target, and Traffic Ingestion reached 32--71% against 30%.

The run made 54,618 HTTP requests (139.95 requests/second), with 0.55% request failures and no interrupted iterations. It **did not meet** the configured latency threshold: p95 HTTP duration was 5.47 seconds, above the 2-second limit. Events show that newly scaled Analytics pods returned readiness 503 while warming; the Job therefore ended with `BackoffLimitExceeded` after k6 exited non-zero for the crossed duration threshold. This establishes HPA scale-out evidence but is not a passing latency result.

## Current state and boundary

The EMR replacement cluster `j-037818516JCX5TXUWKV` reached `WAITING`. Its initially empty step queue was corrected by submitting the existing congestion processor as step `s-06387573MIQ5JCD1V8CI`; that step completed at 12:31:44 UTC. DynamoDB then contained the current workflow's `phase8-535004241f-intersection` congestion summary and its simulated green-extension recommendation. CloudWatch Lambda logs recorded the corresponding congestion alert with `outcome=created` and also recorded the runner-generated incident alert (`03c593f0-ba64-4f94-a718-6d994e5b7ebc/incident-alert/v1`) with `source_type=incident` and `outcome=created`.

The HPAs subsequently downscaled to their configured minima. Runtime resources remain intact. No teardown or audit has been started, and dashboard/central-log coverage evidence and the load latency gap remain Step 3 follow-up work.

## Observability capture and remaining verified gaps

After returning to the permitted EKS network, all four EKS nodes reported `Ready`; Prometheus, Grafana, Alertmanager, Metrics Server, Fluent Bit and the two HPAs were running. Prometheus provided Kubernetes/HPA series (`kube_horizontalpodautoscaler_status_current_replicas` had two series), and the Grafana dashboard definition is provisioned. The HPAs had settled at Analytics 1/1 and Ingestion 2/2 after the load run.

Prometheus's ServiceMonitor discovered all six Kubernetes service targets, but every application `/metrics` scrape returned HTTP 404. Consequently, `smarttraffic_http_requests_total` had no series and the Grafana RPS/error/p95 panels cannot yet display live application data. This is a deployment defect: the current ECR image digests do not expose the instrumentation prepared in Phase 9.

CloudWatch Logs contains Fluent Bit streams for Sensor Registry, Traffic Ingestion, Event Publisher, Signal Recommendation, Incident Manager and Traffic Analytics; Lambda has live alert records. The EMR log group `/smarttraffic/smarttraffic-phase8-emr/emr` has no log streams after the Flink step, so centralized Flink-log coverage is not yet demonstrated. These two defects prevent a truthful claim that the dashboard and all-eight-runtime centralized logging acceptance criteria are complete.

## Metrics-image repair

The six instrumented service images were built, pushed under the immutable `phase9-metrics-20261116` tag, and GitOps-pinned in commit `73db29e`. Argo CD reconciled that commit and all six workloads became ready. Prometheus then reported 22 `smarttraffic_http_requests_total` series and successful `/metrics` scrapes for all six services. Live dashboard queries produced per-service RPS, 5xx-error, p95-latency, and both HPA-current-replica series. The root Argo application remains `Degraded` only because the deliberately retained k6 Job exited non-zero after its recorded p95 threshold breach; the application workloads are ready.

## EMR logging repair limitation

The CloudWatch Agent bootstrap installed and started successfully. An in-place retry added a five-second flush interval, agent-log collection, and the explicitly approved `logs:DescribeLogGroups` permission on the EMR instance role, but repeated privileged marker writes still created no CloudWatch stream. EMR 7.14 supports native CloudWatch `MonitoringConfiguration`, but the installed Terraform AWS provider's `aws_emr_cluster` schema has no matching argument. Creating a replacement cluster through the AWS CLI would create unmanaged infrastructure and violate the Terraform-ownership boundary. Native EMR monitoring therefore requires a separately approved IaC/provider change and a reviewed replacement plan; until then, the all-eight-runtime centralized-log criterion remains incomplete.
