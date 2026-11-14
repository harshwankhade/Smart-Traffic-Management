# Phase 8 DNS bootstrap — certificate apply — 2026-11-14

The user approved the saved `certificate.tfplan`. Terraform applied it from
`infrastructure/terraform/phase8-dns` using the `smarttraffic-sdk` profile.

Result: **3 added, 0 changed, 0 destroyed**.

| Item | Value |
|---|---|
| Hostname | `api.smarttrafficmgmt.online` |
| Region | `ap-south-1` |
| Certificate ARN | `arn:aws:acm:ap-south-1:520646131316:certificate/be73c68e-0709-409e-b7b8-de4121081b6c` |
| Certificate status | `ISSUED` |
| DNS validation | `SUCCESS` |

Terraform created an ACM public certificate, its Route 53 DNS-validation CNAME,
and the certificate-validation state resource. No EKS, ALB, VPC, NAT, MSK, EMR,
RDS, image, GitOps workload, or other Phase 8 infrastructure was created.

Retain this Terraform state, hosted zone, certificate, and validation record while
the later ALB uses the hostname. The full Phase 8 stack must receive the certificate
ARN from this state; it must not request a duplicate certificate.
