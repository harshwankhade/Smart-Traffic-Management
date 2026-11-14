# Phase 8 GitOps delivery boundary

`bootstrap/smarttraffic-root.yaml` is the sole Argo CD root Application. It tracks
`main:deploy/gitops/apps`, where Kustomize defines the `smarttraffic` namespace,
ZooKeeper, and the six Kubernetes application workloads. Argo CD's automated
sync, prune and self-heal are enabled. Every application deployment and update
therefore flows through a reviewed Git revision; direct `kubectl apply` of an
application, Service, Ingress, ConfigMap or workload is forbidden.

Terraform's `argocd_root_application` Helm release seeds only this root
Application during an explicitly authorized Phase 8 run. It must not manage
anything under `apps/`. The root Application creates the namespace, and Argo CD
reconciles all child objects.

Before an authorized sync, replace each `smarttraffic/<service>:phase8-local`
image with the immutable digest pushed to the matching run-scoped ECR repository,
and create the externally managed per-service runtime Secrets: `sensor-registry-runtime`,
`incident-manager-runtime`, `event-publisher-runtime`, `signal-recommendation-runtime`,
and `traffic-analytics-runtime`. They provide only the relevant database URL,
broker/bucket/table/queue identifiers, never static AWS credentials. The Secrets
and per-workload IAM identities are deployment inputs, not Git content.

Render and statically verify manifests without a cluster:

```powershell
kubectl kustomize deploy/gitops/apps
.venv\Scripts\python scripts\phase8_gitops_check.py
```

`kubectl kustomize` only renders local files; it does not contact or change a
cluster. See `docs/phase-8-gitops.md` and `scripts/phase8_acceptance.py` for the
separate, explicitly authorized cloud demonstration workflow.
