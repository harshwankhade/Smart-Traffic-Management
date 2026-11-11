# Infrastructure boundary

Phase 2 includes an [unapplied private SQL foundation](phase2/README.md). AWS/Mumbai and the planned products are approved; costs, account access and quotas remain assumptions pending verification before deployment. No billable deployment is authorized.

Phase 5 adds [a guarded two-table DynamoDB module](phase5/README.md) for a later,
temporary managed verification. It is validated only with Terraform's mock AWS provider;
the access, cost, and explicit deployment gates are recorded in its runbook.

Future Terraform must own all cloud resources and GitOps bootstrap. Keep credentials and state out of source control; select a protected remote state backend before cloud use.
