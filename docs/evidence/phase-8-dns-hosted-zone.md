# Phase 8 DNS bootstrap — hosted-zone apply — 2026-11-14

The user approved the saved `hosted-zone.tfplan`. Terraform applied it from
`infrastructure/terraform/phase8-dns` using the `smarttraffic-sdk` profile.

Result: **1 added, 0 changed, 0 destroyed**.

| Item | Value |
|---|---|
| Hosted zone ID | `Z000164619NSI2EZR8UJP` |
| Public API hostname | `api.smarttrafficmgmt.online` |
| Nameserver 1 | `ns-1319.awsdns-36.org` |
| Nameserver 2 | `ns-1927.awsdns-48.co.uk` |
| Nameserver 3 | `ns-298.awsdns-37.com` |
| Nameserver 4 | `ns-863.awsdns-43.net` |

The only created resource is the public Route 53 hosted zone. No ACM certificate,
validation record, EKS, ALB, VPC, MSK, EMR, RDS, container image, GitOps workload,
or other Phase 8 infrastructure was created.

Next manual action: set all four nameservers at Spaceship for
`smarttrafficmgmt.online`, then wait for public delegation to resolve. Keep this
Terraform state and do not destroy the hosted zone while Spaceship uses these
nameservers, or the domain will stop resolving.
