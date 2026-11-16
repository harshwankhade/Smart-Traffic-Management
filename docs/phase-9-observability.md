# Phase 9 observability and sustained-load runbook

This is a prepared Phase 9 artifact. It does not authorize provisioning or a public HTTPS request.

## GitOps and Terraform ownership

Argo CD applies `deploy/gitops/observability/`: two HPAs, ServiceMonitor, Grafana dashboard and Fluent Bit. Two further Argo CD applications install Metrics Server and `kube-prometheus-stack`. Terraform owns the EKS application-log group, Fluent Bit Pod Identity and EMR CloudWatch bootstrap action. Prometheus retains data for seven days; CloudWatch log groups retain seven days. No request body, event ID, sensor ID or intersection ID is a metric label.

At maximum HPA replicas, application requests total 3.0 CPUs: Ingestion 1.0, Analytics 1.0, Publisher 0.4, Registry/Incident/Recommendation 0.3 and ZooKeeper 0.3. Prometheus, Grafana and four Fluent Bit pods add 0.55 CPUs. Reserving 1.25 CPUs for Kubernetes system components gives 4.8 requested CPUs against the four `t3.large` workers' 8 vCPUs. The remaining capacity is headroom; T3 CPU-credit balance must still be recorded during load.

## Static checks

```powershell
kubectl kustomize deploy/gitops/apps
kubectl kustomize deploy/gitops/observability
.venv\Scripts\python scripts\phase8_gitops_check.py
terraform -chdir=infrastructure/terraform/phase4 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase4 validate
terraform -chdir=infrastructure/terraform/phase8 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase8 validate
.venv\Scripts\python -m unittest tests.test_phase9_metrics -v
```

## Authorized-run evidence sequence

After a fresh cost/plan gate and explicit cloud-run authorization, wait for Argo CD, Metrics Server, Prometheus, Grafana, Fluent Bit and all eight runtimes to become healthy. From an independent trusted network, obtain separate explicit approval and run the strict HTTPS check before load or teardown. Do not disable certificate validation.

Run k6 from a controlled client with unique values:

```powershell
$env:BASE_URL = 'https://api.smarttrafficmgmt.online'
$env:RUN_ID = 'p9-unique-run-id'
k6 run scripts/phase9_load.js
```

Capture Grafana RPS/error/latency, node capacity and CPU credits, HPA replicas before/during/after, k6 summary, EMR/Flink checkpoint counters, Lambda invocation/error/duration, and CloudWatch Logs Insights queries for both domain paths and publisher takeover. Begin teardown within the reviewed window, then preserve Terraform state until the independent absence audit passes.
