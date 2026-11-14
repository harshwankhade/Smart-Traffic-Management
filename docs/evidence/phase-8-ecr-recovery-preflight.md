# Phase 8 ECR recovery preflight — 2026-11-14

This is a review-only checkpoint after the failed integrated run and its teardown. No resource was applied in this checkpoint. The `smarttraffic-sdk` profile resolved to AWS account `520646131316` in the approved `ap-south-1` region. A read-only ECR query returned no `smarttraffic-phase8/` repositories. The integrated Terraform state lists zero resources. The separate DNS/ACM state is retained.

## Exact proposed first apply

The targeted Terraform plan saved at `infrastructure/terraform/phase8/phase8-ecr-recovery.tfplan` (SHA-256 `FDA7C4788F349BE6AB84D8D861ABC7526C1032F2ED8E30AF212A32A83A86C846`) proposes **7 additions, 0 changes, 0 destroys**. The human-readable plan is `infrastructure/terraform/phase8/phase8-ecr-recovery-plan.txt`. Terraform would own six private, immutable, scan-on-push ECR repositories named `smarttraffic-phase8/{sensor-registry,traffic-ingestion,event-publisher,signal-recommendation,incident-manager,traffic-analytics}` and one local `terraform_data.deployment_guard`. The target is exceptional staging to publish images before the integrated stack; it is not a replacement for the full plan. No EKS, MSK, EMR, NAT, RDS, or ALB resource is in this first apply.

## Cost and remaining gates

Cost Explorer returned estimated November 1–14 unblended usage of **US$6.6381271926** (query end November 15), leaving US$3.3618728074 under the original US$10 total cap and US$2.8618728074 under its US$9.50 predeployment gate. Prior failed-run charges may post later. The user waived the cap for the Phase 8 Step 4 run, but plan review and explicit apply approval remain required.

AWS ECR private-repository pricing charges for stored data, with no repository creation fee. The six existing local images each show about 698 MB of uncompressed Docker image size. A rough conservative storage calculation using six times 0.698 GB and AWS's published **US$0.10/GB-month example** is about **US$0.42/month**, or about US$0.014 for one day, before any applicable free-tier allowance; actual stored compressed size, regional billing, and duration determine the charge. ECR data transfer in is free; same-region transfers to AWS services are free under the cited pricing example. The retained Route 53 hosted zone has its separate US$0.50/month charge and is unaffected by this plan.

After an expressly approved ECR-only apply, build/push the six images, update GitOps digest pins, and push that Git revision before an Argo CD bootstrap. The later full-stack plan and current cost/access gates require separate review and authorization. Do not use the old digest pins: teardown deleted those images.

## Approved apply result

The user explicitly approved this exact seven-addition ECR recovery plan. The saved plan hash was rechecked against the value above; STS again returned account `520646131316`, and the six repository names were absent before apply. `terraform apply phase8-ecr-recovery.tfplan` completed with **7 added, 0 changed, 0 destroyed**. `terraform state list` contains exactly six `aws_ecr_repository.services` instances and the `terraform_data.deployment_guard`. A separate `aws ecr describe-repositories` query in `ap-south-1` found all six expected repository URLs with `IMMUTABLE` tags. The targeted-plan warning is expected: the remaining integrated stack was deliberately outside this apply. No images were pushed and no full-stack apply was run in this step.

## Image publication and refreshed integrated plan

On the user's subsequent instruction to continue, `scripts/phase8_publish_images.py` built and pushed all six images under immutable `phase8-run` tags in the six Terraform-owned repositories. ECR returned these digests, which match the local changes in `deploy/gitops/apps/kustomization.yaml`:

| Service | ECR image digest | Stored image bytes |
|---|---|---:|
| sensor-registry | `sha256:21d574488230a38409f1a94d6eece9cb67061b7d3020a4bf5e7e5a49923659cf` | 238473598 |
| traffic-ingestion | `sha256:4b8aa54631d268b16b7e3baa6af75cb564382d2038d293340d46d8a84555a383` | 238473513 |
| event-publisher | `sha256:eb672592e6a49199c9b62d50944bdad12f66a0a5d626f932a0614bb97c1102df` | 238473586 |
| signal-recommendation | `sha256:939879e120b942952e24e2a57e48d69cee0e4ccf483901644b48d41cd70c3e3a` | 238473639 |
| incident-manager | `sha256:8a115e2483ada52117fee4ffabfc36cba30b2f334079b19223b4fbf7eb55b688` | 238473565 |
| traffic-analytics | `sha256:185f3a6a70dae8ac4212f1d86425acd4b4e3fcfcaa5224793e02b704eccabda0` | 238473590 |

The six stored image sizes sum to about 1.431 GB. At AWS's illustrative US$0.10/GB-month ECR rate, this is approximately US$0.14/month before any free tier; actual account charges may differ. Cost Explorer still returned estimated November unblended usage of US$6.6381271926 immediately before publication and may lag these uploads. The temporary Docker registry token file was removed after publication.

`kubectl kustomize deploy/gitops/apps` rendered all six digest-pinned images. `scripts/phase8_gitops_check.py` passed its local ownership, workload, ZooKeeper, HTTPS ingress, and External Secrets checks. The GitOps manifest change remains uncommitted and unpushed, so Argo CD cannot see it yet.

A refreshed enabled full Terraform plan against the seven state-owned ECR-stage resources returned **132 additions, 0 changes, 0 destroys**. The saved plan is `infrastructure/terraform/phase8/phase8-post-ecr-review.tfplan` (SHA-256 `63E2A1402E967E6F33DBAD52B47F8253CF87E518326ADA78915B544F57BC0226`), with readable output in `infrastructure/terraform/phase8/phase8-reviewed-plan.txt`. The full stack was not applied. Before that apply, push the pinned GitOps revision, review the current full-stack cost/access gate and exact plan, and obtain explicit approval.

The user subsequently approved the deployment continuation and waived the US$10 total cap for the duration of Phase 8. This changes the Phase 8 spending gate only; the separate DNS hosted zone remains and the review, technical-readiness, acceptance, and teardown gates still apply.
