# Phase 8 EKS failure diagnosis and recovery proposal

Checked 2026-11-15. Recovery is in progress. Phase 8 remains incomplete; runtime resources remain billable.

## Recovery execution update

The S3 endpoint policy in `infrastructure/terraform/phase3/main.tf` now allows `s3:GetObject` for `arn:aws:s3:::prod-ap-south-1-starport-layer-bucket/*`. Terraform format and validation passed. Saved targeted plan `phase8-ecr-layer-fix.tfplan` showed **0 add, 1 in-place change, 0 destroy** and applied successfully. Restarting only the failed EKS system pods caused both workers to become `Ready`; both `aws-node`, both `kube-proxy`, and both CoreDNS pods became healthy. This directly verifies the diagnosed cause.

The managed node group nevertheless remained `CREATE_FAILED`, and Terraform marked it tainted. A full plan proposed an unrelated EMR replacement because live `os_release_label` differs from the configuration's null value; this plan was **not applied**. Saved targeted `phase8-nodegroup-recovery.tfplan` showed **1 add, 0 change, 1 destroy** for the node group only. Its apply replaced the failed group. Follow-up inspection found the replacement `ACTIVE` with no health issues, both new workers `Ready`, and the CNI, kube-proxy, and CoreDNS pods healthy. Terraform state records the new group as normal, not tainted. The node group recovery is verified; the unrelated EMR plan drift and remaining platform/GitOps bootstrap still need work before Phase 8 acceptance.

## Confirmed evidence

- Both workers (`i-09827be2a5bf98bda`, `i-059a4701db0928c17`) registered with Kubernetes and remain `NotReady`. This is a node readiness failure, rather than a failure to authenticate/register.
- Node condition: `KubeletNotReady`, `NetworkPluginNotReady`, `cni plugin not initialized`.
- `aws-node` init containers and `kube-proxy` are in `ImagePullBackOff`; CoreDNS is pending. The layer download returns `403 Forbidden` from `prod-ap-south-1-starport-layer-bucket.s3.ap-south-1.amazonaws.com`. Signed URLs and temporary tokens are deliberately omitted from evidence.
- Gateway endpoint `vpce-097015d71bda37b35` serves the workers' shared private route table. Its policy allows only the project archive and selected EMR/repository/log buckets. It omits the regional ECR layer bucket.
- The managed node role is present in `kube-system/aws-auth`; its attached policies are `AmazonEKSWorkerNodePolicy`, `AmazonEC2ContainerRegistryPullOnly`, and `AmazonEKS_CNI_Policy`.
- Both private subnets have an active NAT route. The EKS private endpoint is enabled. The public endpoint remains restricted to `103.144.92.233/32`.
- Terraform state records `aws_eks_node_group.main` as **tainted** and retains the endpoint and existing resources. The apply exited unsuccessfully; no concurrent apply remains from that run.

AWS diagnostic automation `70c6ccd2-ed85-4277-ad40-15a036f38c23` completed successfully. It passed cluster SG, DHCP/DNS, cluster IAM, control-plane ENIs, EC2 health, NAT placement, node trust, bootstrap configuration, AMI compatibility, NACL, STS and IMDS checks for the first worker. It could not inspect system services or run in-node DNS tests because SSM was unavailable. Its instance-type check errored internally; its overall report is not an exhaustive pass.

## Cause and confidence

ECR obtains image manifests through the registry, then downloads image layers from an AWS-owned S3 bucket. The S3 gateway route takes precedence over NAT for matching S3 destinations. NAT availability therefore cannot bypass the restrictive endpoint policy. The missing bucket allow explains the observed S3 403, stalled CNI initialization, node `NotReady`, and eventual managed node group `CREATE_FAILED`.

This is the demonstrated blocker, with high confidence. Applying and verifying the correction is still required to prove resolution; subsequent application failures have not been ruled out.

AWS documents precisely this bucket and action in [Minimum Amazon S3 bucket permissions for ECR](https://docs.aws.amazon.com/AmazonECR/latest/userguide/vpc-endpoints.html).

## Minimal correction

Add a separate statement to the existing endpoint policy in `infrastructure/terraform/phase3/main.tf`, used by Phase 8 as `module.streaming`:

```hcl
{
  Sid       = "AllowRegionalECRImageLayers"
  Effect    = "Allow"
  Principal = "*"
  Action    = ["s3:GetObject"]
  Resource  = "arn:aws:s3:::prod-ap-south-1-starport-layer-bucket/*"
}
```

Preserve every existing project/EMR statement. This permits only reads of the regional ECR layer bucket through the endpoint. It does not grant public access to project storage or override S3/IAM authorization, disable TLS, open the EKS endpoint, or require additional infrastructure. Do not grant S3 wildcard access, remove the endpoint, or broaden worker IAM to address this error.

The diagnostic automation flags absent `ecr:BatchCheckLayerAvailability`. This is not established as an additional cause: AWS currently recommends the already-attached [AmazonEC2ContainerRegistryPullOnly policy for EKS nodes](https://docs.aws.amazon.com/eks/latest/userguide/create-node-role.html). Its [policy document](https://docs.aws.amazon.com/aws-managed-policy/latest/reference/AmazonEC2ContainerRegistryPullOnly.html) omits that action. Our image pulls reached S3 layer downloads. Retain current IAM unless a subsequent real API denial demonstrates another permission is needed. Likewise, the runbook's missing *managed* CNI/kube-proxy add-on warnings do not mean their existing self-managed DaemonSets are absent; live Kubernetes confirms they exist. Converting add-on ownership is unnecessary for this repair.

## Ordered recovery procedure and remaining checks

1. Preserve the existing Terraform state and take a protected local backup. Make the endpoint policy correction, run `fmt -check` and `validate` for the affected roots, and save/review a fresh **endpoint-only** plan targeting `module.streaming.aws_vpc_endpoint.s3`. Expect one policy update, zero additions/deletions. Use the current run's exact variable inputs. Apply only that saved, reviewed plan when execution is authorized. Targeting is justified for this exceptional recovery; a complete plan must follow it.
2. Allow policy propagation and watch the existing nodes before deleting anything. Require successful CNI/kube-proxy image pulls, `aws-node` readiness, both nodes `Ready`, and CoreDNS readiness. Kubelet retries automatically; do not directly deploy application manifests. If 403 persists, inspect a fresh error's bucket and endpoint policy before adding permissions. Do not retry an unchanged node group blindly.
3. Produce a fresh **full** Terraform plan. The current tainted node group is expected to be replaced; inspect the exact diff. Preserve the EKS control plane, MSK, EMR, RDS, buckets, DNS and certificate. Existing nodes becoming Ready does not by itself clear the AWS `CREATE_FAILED` managed group status. Do not untaint or remove it from state to hide the failed creation. Review/authorize the replacement and pending platform bootstrap before applying the saved full plan. If unexpected replacement of data services appears, stop and investigate.
4. Verify the replacement node group is `ACTIVE` with no health issues, both workers are `Ready`, CNI/kube-proxy/CoreDNS are healthy, and the Pod Identity agent becomes healthy. Then verify Terraform-owned controllers and Argo CD bootstrap. GitOps must reconcile the six applications and ZooKeeper. Check workload image pulls (the same ECR layer permission is needed), identities, runtime secrets, private data connectivity, ALB HTTPS, and DNS before running the existing Phase 8 acceptance workflow. This fixes a provisioning blocker; it does not prove end-to-end acceptance.
5. Capture the affected checks and final full plan/state result, then follow the approved Phase 8 lifecycle and teardown/audit. Retain the separate DNS/certificate state. If recovery fails, record the new concrete error and avoid leaving expensive resources idle indefinitely.

Useful read-only readiness checks, using the task-local kubeconfig:

```powershell
$env:AWS_PROFILE = 'smarttraffic-sdk'
$env:KUBECONFIG = Join-Path (Get-Location) '.data/phase8/diagnostic-kubeconfig'
kubectl get nodes -o wide
kubectl -n kube-system get pods -o wide
kubectl -n kube-system rollout status daemonset/aws-node --timeout=180s
kubectl -n kube-system rollout status daemonset/kube-proxy --timeout=180s
kubectl -n kube-system rollout status deployment/coredns --timeout=180s
aws eks describe-nodegroup --region ap-south-1 --cluster-name smarttraffic-phase8 --nodegroup-name application --query 'nodegroup.{status:status,issues:health.issues}'
```

## Cost and limits

The policy statement creates no new billable resource. Node replacement and further running time incur usage charges. The prior reviewed baseline was approximately US$0.90/hour for the complete stack, before storage, requests, transfer and other charges; this is historical planning context, not a fresh measured bill or ceiling. The full plan requires the EMR drift issue to be resolved before apply. No application deployment, architecture change, or security relaxation has been performed in this recovery so far.
