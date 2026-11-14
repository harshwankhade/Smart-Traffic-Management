# Phase 8 failed run and teardown — 2026-11-14

The approved integrated apply created a partial stack but did not reach GitOps or acceptance. The EKS managed node group entered `CREATE_FAILED` with `NodeCreationFailure` for instances `i-0a3247899893d0f6b` and `i-09689f352714e94d6`. EC2 console output shows `nodeadm` and kubelet started; the node registration failure needs further diagnosis. The private route table had an active default route through an available NAT gateway. EMR cluster `j-03952081A4VGPU0NICD9` entered `TERMINATED_WITH_ERRORS`: `VALIDATION_ERROR`, service role had insufficient EC2 permissions. No public ALB or Argo workloads were verified.

Teardown was authorized as part of Phase 8 Step 4. The destroy plan contained 123 tracked resources. Terraform removed the runtime resources but could not delete six ECR repositories containing images, because their saved state did not have `force_delete`. The six exact `smarttraffic-phase8/*` repositories were then deleted with ECR `--force`. A refreshed final Terraform plan removed the remaining deployment guard. The integrated Terraform state now lists zero resources.

Independent AWS queries found no matching EKS, MSK, RDS, ECR, active EMR, DynamoDB, S3, Lambda, or SQS run resources. The NAT gateway is `deleted`. The separate `phase8-dns` state was untouched: hosted zone `Z000164619NSI2EZR8UJP` remains for `smarttrafficmgmt.online`, and the ACM certificate for `api.smarttrafficmgmt.online` remains `ISSUED`.

Step 4 is incomplete. Before another cloud apply, diagnose EKS node registration, correct the EMR role permissions, and generate a fresh reviewed plan. Cost Explorer charges may post after teardown.

## Follow-up diagnosis and configuration correction

AWS's `AmazonEMRServicePolicy_v2` requires the predefined `for-use-with-amazon-emr-managed-policies=true` tag on the subnet and custom security groups used by EMR. The custom EMR security groups already had the tag; the Phase 8 private subnet did not. Terraform now tags the private subnets, which addresses the reported service-role EC2 permission failure without broadening the role policy.

The EKS worker console showed `nodeadm` and kubelet starting, and the private NAT route was active when inspected, but there was no kubelet registration error in the captured console output. The exact node failure remains unproven. Terraform now orders the public NAT subnet's internet route and route-table association before NAT creation, and orders the managed node group after the private NAT route and private route-table associations. A future authorized run must inspect node registration immediately if it fails again; these ordering changes alone are not evidence that the issue is resolved.

The teardown deleted the six ECR repositories and their images. Existing GitOps digest pins therefore refer to deleted images. Before another integrated apply, a separately reviewed ECR-only stage must recreate the repositories, then the image-publishing script must rebuild/push the six images and update GitOps digest pins in a pushed commit. The new full-stack plan is for review only; it does not by itself restore deployable images.

After these edits, `terraform fmt -check -recursive` and `terraform validate` passed. A fresh enabled plan against the empty integrated state and AWS account `520646131316` returned **139 additions, 0 changes, 0 destroys**. Its saved historical binary plan is `phase8-retry-review.tfplan`. No full-stack apply was run. The EKS registration cause must be investigated during a future authorized run if it recurs.
