# Infrastructure boundary

Phase 2 includes an [unapplied private SQL foundation](phase2/README.md). AWS/Mumbai and the planned products are approved; costs, account access and quotas remain assumptions pending verification before deployment. No billable deployment is authorized.

Future Terraform must own all cloud resources and GitOps bootstrap. Keep credentials and state out of source control; select a protected remote state backend before cloud use.
