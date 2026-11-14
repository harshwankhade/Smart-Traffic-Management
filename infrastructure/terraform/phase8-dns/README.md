# Phase 8 DNS and certificate bootstrap

This Terraform state is intentionally separate from `../phase8`. It owns or reuses
the public Route 53 hosted zone for `smarttrafficmgmt.online`, the ACM certificate for
`api.smarttrafficmgmt.online`, and ACM's DNS-validation CNAME record. It does not
create EKS, MSK, EMR, RDS, VPC, ALB, ECR, Lambda, SQS, or any Kubernetes resource.

## State and delegation lifecycle

Keep the generated `terraform.tfstate` with this root until the domain is retired
or the state has been migrated to an approved remote backend. Do not destroy the
hosted zone while Spaceship delegates the domain to its nameservers: doing so makes
the domain unreachable. During full Phase 8 teardown, retain this DNS state and
hosted zone if the public hostname/certificate may be reused. Destroy it only after
changing Spaceship nameservers away from Route 53 and confirming DNS propagation.

## Two safe, narrow stages

1. **Hosted-zone stage** — plan with `certificate_enabled=false`. With
   `existing_hosted_zone_id=null`, it creates one billable public hosted zone. Set that
   variable to an existing zone ID to reuse it instead. After approval, apply only the
   saved plan, then copy
   `route53_nameservers` into Spaceship's custom-nameserver settings for the domain.
2. **Certificate stage** — once public DNS delegation resolves to all four Route 53
   nameservers, plan with `certificate_enabled=true`. It creates an ACM public
   certificate and one Route 53 validation CNAME. The ACM certificate has no charge
   when attached to the future ALB. Apply only after reviewing that second plan.

Commands to prepare each plan:

```powershell
terraform -chdir=infrastructure/terraform/phase8-dns init -backend=false -input=false
terraform -chdir=infrastructure/terraform/phase8-dns fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase8-dns validate
terraform -chdir=infrastructure/terraform/phase8-dns plan -var-file=terraform.tfvars.example -out=hosted-zone.tfplan
# After delegation is confirmed, change only certificate_enabled to true.
terraform -chdir=infrastructure/terraform/phase8-dns plan -var-file=terraform.tfvars -out=certificate.tfplan
```

Expected first-stage cost: a newly created Route 53 public hosted zone costs US$0.50
per month; reusing a zone adds no hosted-zone charge. DNS query
charges are negligible for this bootstrap. ACM public certificates used by ALB have
no certificate charge. Never run an apply until the exact saved plan and cost have
been reviewed and explicitly approved.

After the certificate succeeds, provide these outputs to the later Phase 8 stack:

```powershell
terraform -chdir=infrastructure/terraform/phase8-dns output hosted_zone_id
terraform -chdir=infrastructure/terraform/phase8-dns output -json route53_nameservers
terraform -chdir=infrastructure/terraform/phase8-dns output public_api_hostname
terraform -chdir=infrastructure/terraform/phase8-dns output public_api_certificate_arn
```
