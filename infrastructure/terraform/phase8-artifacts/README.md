# Retained demo build storage

This separately guarded Terraform root owns the six immutable ECR repositories and a private, encrypted, versioned S3 cache for Lambda/Flink binaries. It has no EKS, MSK, EMR, NAT, database or application deployment. Retain this state between runtime runs; storage charges continue. Bucket/repository `prevent_destroy` safeguards and disabled force deletion are intentional.

Use `terraform init -backend=false`, `fmt -check`, `validate`, and `test` for preparation. Tests mock AWS and only plan. Before an enabled AWS plan/apply, refresh inventory/costs and obtain separate authorization. The default `deployment_approved=false` blocks provisioning. If repositories already belong to runtime state, review a state migration before using this root; never create two owners or delete/recreate them to change ownership.

Outputs: `ecr_repositories` for `scripts/phase8_publish_images.py`, and `build_bucket` for the optional remote cache in `scripts/prepare_demo_artifacts.py`. See [the complete workflow](../../../docs/reduced-startup.md).
