# Phase 8 integrated deployment design and preflight

**Status: proposed for approval (2026-11-12).** This is Phase 8 Step 1 only. It records a deployable target and the gates that prevent an apply. It creates no AWS resources, and it does not approve Phase 8 Steps 2–5.

## Existing baseline and required outcome

The repository has separately guarded, temporary Terraform roots: private RDS/network (`phase2`), MSK/S3 (`phase3`), EMR 7.14/Flink 1.20 (`phase4-live`), DynamoDB (`phase5`), and SQS/Lambda (`phase6`). All prior managed resources were removed. The six Python services have no Dockerfiles or Kubernetes manifests, and `deploy/gitops/` is a placeholder. The Git remote is `https://github.com/harshwankhade/Smart-Traffic-Management.git` on `main`.

Phase 8 must replace the temporary composition with one guarded, run-scoped integrated root. It must run exactly six services on EKS, Flink on EMR on EC2, and Alert Service on Lambda; use RDS PostgreSQL, DynamoDB and S3; and deploy Kubernetes workloads only through Git reconciliation.

## Proposed target design

| Area | Proposed Phase 8 choice | Boundary |
|---|---|---|
| Region and network | `ap-south-1`; a new two-AZ VPC with public ALB subnets and private EKS, MSK, EMR and RDS subnets. No public database or broker endpoints. | Terraform owns VPC, routes, security groups and endpoints. |
| Private egress | One NAT gateway in a public subnet is required if Argo CD in private EKS subnets must read this GitHub repository. Retain the S3 gateway endpoint and evaluate ECR API/DKR, STS and CloudWatch Logs interface endpoints to reduce private-service traffic. | GitHub has no VPC endpoint; a no-NAT design would prevent normal Argo CD Git access unless an approved private Git mirror replaces it. |
| Kubernetes and GitOps | One standard-support EKS cluster with a small managed node group; Terraform installs/bootstraps Argo CD. Argo CD reads this repository's `main` branch and owns namespaces, ZooKeeper, and all six application workloads. | Terraform must never manage an application Deployment, StatefulSet, Service or Ingress. No direct `kubectl apply` for applications. |
| ZooKeeper | A three-replica, EBS-backed ZooKeeper StatefulSet in EKS, reconciled by Argo CD. It remains infrastructure, not a ninth application service. | The existing Phase 7 ephemeral-sequential election contract remains unchanged. |
| Kafka and Flink | Private two-broker MSK Provisioned Standard (`kafka.t3.small`), TLS/IAM authentication, `traffic.raw` and `traffic.results`; EMR 7.14 with Flink 1.20 in the same VPC, using S3 for JAR/archive/checkpoints. | Retain the Phase 4 result contract, at-least-once sink and bounded deduplication limits. |
| Data and alerts | Private single-AZ RDS PostgreSQL for Registry/Incident Manager; the three owner-scoped DynamoDB tables for recommendations, summaries and alerts; one private S3 archive/checkpoint bucket; SQS Standard + DLQ and Lambda Alert Service. | Each service retains its current record ownership and deterministic identifiers. |
| Identity and secrets | EKS Pod Identity or IRSA roles per workload, a distinct EMR role pair and Lambda role. Store generated RDS credentials in Secrets Manager and inject references at runtime; no static credentials in Git, manifests or image layers. | IAM policies must remain scoped to each service's tables, queue, bucket prefix and Kafka topic/group. |
| Public entry | Internet-facing ALB with ACM TLS and a public HTTPS route only for approved REST APIs. EKS API access is restricted to the authorized administrator network; gRPC, Kafka, ZooKeeper, RDS and DynamoDB remain private. | The exact public host name, administrator CIDR and application authentication/rate-limit method need approval. |
| Images | Build six Linux `linux/amd64` images from repository Dockerfiles in Step 2, push immutable image digests to Terraform-created private ECR repositories, and reference those digests from GitOps manifests. | Lambda retains its separately built ZIP; EMR retains the approved EMR JAR build. |

## Terraform and GitOps ownership

Terraform must own the VPC/endpoints, EKS control plane/node group/add-ons, ECR, MSK/topics, EMR, RDS, DynamoDB, S3, SQS/DLQ, Lambda, IAM, ACM/ALB infrastructure, and Argo CD bootstrap. Argo CD must own every Kubernetes workload and its configuration: namespaces, service accounts, ConfigMaps, external-secret references, ZooKeeper, Services, Deployments, StatefulSets, HPAs later in Phase 9, and Ingress objects. The controller is installed by Terraform, then manages its own Application definitions and all application changes from Git.

## Resource inventory and lifecycle

| Resource group | Create for a run | Teardown/audit requirement |
|---|---|---|
| Network/EKS/ECR/ALB/ACM/endpoints | VPC, two-AZ subnets/routes, security groups, endpoints, EKS, node group, EBS volumes, ECR repos, ALB/TLS resources | Destroy through the run's Terraform state; inspect EKS, EC2 networking, ELB, ECR and EBS for run tags/identifiers. |
| Streaming/processing/storage | MSK cluster/configuration/topics, EMR cluster/roles/logs, S3 bucket and objects, RDS instance/subnet/parameter groups | Stop EMR, empty only the run-owned versioned bucket, destroy, then query EMR/MSK/S3/RDS/IAM residue. |
| Data/alerts | Three DynamoDB tables, SQS/DLQ, Lambda, event mapping, log groups and scoped roles/policies | Destroy, confirm empty state, then query table/queue/function/log/IAM identifiers. |
| GitOps workloads | Argo CD reconciles only tagged/digest-pinned run manifests | Before Terraform destroy, remove the GitOps Application through the approved Git revision and wait for pruning; no manual application deletion. |

Every resource must use a unique run prefix and `Project=smarttraffic`, `Phase=8`, and `Run=<id>` tags. A run must be supervised through provisioning and must preserve Terraform state until independent cleanup succeeds. A failure still requires the same cleanup/audit path.

## Access, quota and cost preflight

The restored `smarttraffic-sdk` profile was verified on 2026-11-12. It resolves to root principal/account `520646131316` in `ap-south-1`. Read-only inventory found no Smart Traffic-prefixed EKS, MSK, active EMR, RDS, DynamoDB, S3, SQS or Lambda resources. The available zones are `ap-south-1a`, `1b` and `1c`. The checked quotas have headroom: 100 EKS clusters and 450 nodes per managed node group; 90 MSK brokers per account and 30 per cluster; 500 active EMR clusters; 20 RDS DB instances; and 10 Lambda concurrent executions. These checks do not prove every service dependency or permission needed for a later apply.

The exact read-only commands and returned values are in [`docs/evidence/phase-8-preflight.md`](../evidence/phase-8-preflight.md).

Cost Explorer reported **US$6.4865880038** estimated unblended account usage for 1–13 November. The approved project cap is **US$10.00** with a **US$0.50** reserve, so the current predeployment gate is US$9.50. On that lagging, account-wide figure, **US$3.5134119962** remains below the cap and **US$3.0134119962** remains below the gate. The service breakdown includes Kinesis, KMS and tax, so it cannot be attributed solely to this project; it still does not prove that an integrated deployment is affordable.

This full Phase 8 design cannot fit the currently proven headroom. AWS lists EKS standard support at US$0.10 per cluster-hour before worker nodes, storage and networking. EMR on EC2 adds EMR charges to EC2 and EBS charges; MSK charges per broker plus storage. RDS, the required NAT gateway for GitHub-based Argo CD, load balancing, private interface endpoints, logs, data transfer and public IPv4 can add further costs. A current, account-specific AWS Pricing Calculator estimate is required after selections and before any apply. It must include realistic provisioning time, not only the 20-minute demonstration.

References: [EKS pricing](https://aws.amazon.com/eks/pricing/), [MSK pricing](https://aws.amazon.com/msk/pricing/), [EMR pricing](https://aws.amazon.com/emr/pricing/), [RDS PostgreSQL pricing](https://aws.amazon.com/rds/postgresql/pricing/), and [AWS Pricing Calculator guidance](https://docs.aws.amazon.com/pricing-calculator/latest/userguide/getting-started.html).

## Required approvals and gates before Step 2

1. Approve or revise the proposed EKS/Argo CD/ZooKeeper, two-AZ private network, public-ALB and endpoint design.
2. Choose a public DNS name, the permitted administrator CIDR, and the public API authentication/rate-limit approach.
3. Restore an authorized AWS profile and obtain read-only evidence for identity, region availability, relevant EKS/MSK/EMR/RDS/Lambda quotas, current resource inventory and Cost Explorer.
4. Produce a dated Mumbai calculator estimate, set a run duration and cleanup time limit, and explicitly approve a revised cap if the estimate cannot fit the remaining budget.
5. Confirm GitHub access that lets Argo CD read the repository and determine the secret-delivery mechanism for that credential, if the repository remains private.

## Likely Step 2 files

- A new guarded `infrastructure/terraform/phase8/` root, replacing reuse of temporary roots.
- Six service Dockerfiles and `.dockerignore` files; ECR/image build instructions.
- `deploy/gitops/` Argo CD bootstrap/application definitions and a repository layout for the six services plus ZooKeeper.
- Cloud configuration/secrets-reference support, focused packaging checks and an apply/teardown runbook.

No interface, service-boundary or behavior change is approved by this document. Phase 8 remains **In Progress** pending the approvals and access/cost gates above.

## Step 2 preparation result

The new integrated Terraform root, shared six-service image definition and package checker are prepared. Terraform formatting and validation passed; the false deployment guard stopped plan-only review before creation. Docker Desktop was unavailable, and the Phase 3 child Terraform provider still cannot refresh its own credential process under the restored profile, so no enabled plan was generated. See `docs/phase-8-iac.md` for the exact checks, remaining inputs and teardown sequence. This does not authorize an apply or Step 3.
