# Phase 8 Step 3: GitOps and integrated acceptance preparation

Status: **prepared and statically validated; not deployed**. Argo CD receives one
Terraform-seeded root Application, `smarttraffic-root`. It reconciles the Git
revision at `main:deploy/gitops/apps` with automated prune and self-heal. The
Git tree owns the namespace, private ClusterIP services, six workload service
accounts and deployments/statefulset, runtime ConfigMap, NetworkPolicies, public
HTTPS Ingress routes, and a child Argo Application for three-replica ZooKeeper.
Terraform must not manage those objects; direct `kubectl apply` of any application
object is prohibited.

The six workloads use private DNS. Traffic Ingestion resolves Registry and the
elected Event Publisher via ZooKeeper; Event Publisher is a two-replica StatefulSet
with per-pod gRPC addresses. Readiness probes use dependency-aware `/readyz` where
the service provides one; basic APIs use `/healthz`. The public Ingress exposes
only documented REST paths. Its public DNS name and ACM ARN are now the approved
`api.smarttrafficmgmt.online` and regional certificate. Terraform creates scoped
Pod Identity associations for every workload and External Secrets; the Git-tracked
ExternalSecret retrieves only a runtime-reference record, while Registry and
Incident Manager read the RDS-generated password through their own identities.
No credential is committed. Before Argo's first sync, the staged ECR publisher
writes the six immutable image digests into Kustomize.

`scripts/phase8_acceptance.py` defaults to a static, cloud-run-locked workflow.
After separate authorization, `--cloud-run --allow-cloud-run` requires the public
endpoint plus resource identifiers, exercises REST-to-private-gRPC-to-Kafka-to-EMR
Flink, polls recommendation/analytics results, creates an incident, and read-only
checks S3, DynamoDB, SQS, Lambda and EMR. The operator must additionally capture
Argo sync status, all six workload readiness, ZooKeeper leader/follower status and
failover after a Git-driven rollout. Cleanup begins by removing the root Application
through a Git commit and waiting for Argo prune; only then may the existing
Terraform teardown/audit procedure run.

Following approved ownership correction, Terraform now installs the AWS Load
Balancer Controller through Helm, gives only its `kube-system` service account an
EKS Pod Identity role, and derives that role policy from the pinned upstream
controller `v2.14.1` policy. Terraform retains the ACM certificate; the controller
creates and owns the ALB/listeners/target groups required by the GitOps Ingress.
The former Terraform ALB has been removed, so the two systems do not compete for
the same load-balancing resources. Terraform also bootstraps ExternalDNS with a
separate Pod Identity role limited to the approved Route 53 hosted zone; it creates
the Ingress hostname alias after the controller publishes the ALB address.

Checks run on 2026-11-14: `kubectl kustomize deploy/gitops/apps` rendered locally;
`scripts/phase8_gitops_check.py` verified root ownership, all six service manifests,
ZooKeeper, HTTPS ingress and External Secrets references. Terraform formatting and
`validate` passed; the Phase 2 database regression tests passed. No Kubernetes
cluster, AWS resource, Terraform apply or cloud demo was run.

Before a separately authorized run, create only the ECR repositories from the
reviewed state, run `scripts/phase8_publish_images.py`, commit/push the generated
digest pins, then apply the remaining reviewed root. ExternalDNS, not a manual
console change, creates the Route 53 alias.
