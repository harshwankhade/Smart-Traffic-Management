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

Before an authorized sync, create the six ECR repositories in the reviewed,
ECR-only Terraform stage, then run `scripts/phase8_publish_images.py` to build,
push, and write immutable digest pins into `apps/kustomization.yaml`. Commit and
push that revision before the Argo CD root Application is installed.

Terraform stores only resource identifiers and RDS secret ARNs in the named
Secrets Manager runtime-reference record. External Secrets materializes those
values as `smarttraffic-runtime-values`; the Registry and Incident Manager use
their scoped Pod Identity roles to retrieve the generated RDS password directly.
No password, static AWS credential, or runtime Secret is committed to Git.

Render and statically verify manifests without a cluster:

```powershell
kubectl kustomize deploy/gitops/apps
.venv\Scripts\python scripts\phase8_gitops_check.py
```

`kubectl kustomize` only renders local files; it does not contact or change a
cluster. See `docs/phase-8-gitops.md` and `scripts/phase8_acceptance.py` for the
separate, explicitly authorized cloud demonstration workflow.
