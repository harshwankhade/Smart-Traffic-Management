# Phase 8 DNS and certificate bootstrap

**Status: prepared; no resources created.** The approved public HTTPS architecture
remains an ACM certificate on the application load balancer in `ap-south-1`. The
new `infrastructure/terraform/phase8-dns/` state separates domain delegation and
certificate validation from EKS, MSK, EMR, RDS, NAT, and GitOps provisioning.

The selected API hostname is `api.smarttrafficmgmt.online`. Its root domain was
purchased through Spaceship. Terraform either creates a new Route 53 public hosted
zone or reads a supplied existing one. It exposes the hosted-zone ID and Route 53's
four nameservers. After Spaceship delegates the domain to those nameservers, the
second stage requests ACM's DNS-validated certificate in `ap-south-1` and creates
the validation CNAME. The later Phase 8 state receives the resulting certificate
ARN instead of attempting to create another certificate.

The first-stage expected billable resource is one Route 53 hosted zone: US$0.50 per
month when creating a new zone, plus negligible DNS queries. An ACM public
certificate used with the future ALB has no certificate charge. No cost estimate for
the expensive integrated stack is implied by this bootstrap.

Keep this Terraform state after application teardown. It owns delegation and the
certificate; deleting the hosted zone while Spaceship still uses its nameservers
breaks DNS. Retire it only after Spaceship nameservers have changed and propagation
has been confirmed.

The exact plan has not been generated because the expected AWS profile session has
expired. Reauthenticate it, then run the commands in the DNS root README. Review the
saved first-stage plan before any apply and provide its output for approval.
