# Phase 3 MSK/S3 preparation - unapplied

This root uses AWS provider 6.45.0 and creates no resources until a separately reviewed deployment is approved. Only `init -backend=false`, formatting checks, `validate` and mocked `test` are authorized. Do not run an AWS-backed plan or apply under the current US$5/no-credit budget assumptions.

```powershell
terraform -chdir=infrastructure/terraform/phase3 init -backend=false -input=false
terraform -chdir=infrastructure/terraform/phase3 fmt -check -recursive
terraform -chdir=infrastructure/terraform/phase3 validate
terraform -chdir=infrastructure/terraform/phase3 test
```

`init` downloads the pinned provider; both tests use a mock AWS provider and plan-only execution. One expects the default deployment precondition to fail; the other inspects the intended configuration. These are not MSK, S3, networking or IAM deployment proofs.

Supply existing Phase 2 outputs as `vpc_id`, `private_subnet_ids`, `application_security_group_id` and `private_route_table_ids` before future planning. Test fixtures use clearly mocked IDs. Do not replace real inputs with fixtures. There is no second VPC/RDS in this root. The S3 gateway endpoint extends the existing private route tables, and new application egress rules allow Kafka IAM TLS 9098 and HTTPS to the S3 prefix list. Kafka broker security-group traffic is self-restricted; no public client listener is defined.

The intended MSK cluster is two Standard kafka.t3.small brokers using 3.9.x and 10 GiB storage per broker. Topic `traffic.raw` has one partition, RF=2, minISR=2 and 24-hour retention. Broker failure may halt writes. Standard-tier instance/version/storage availability and topic-management API permissions need actual regional verification before deployment.

The archive bucket blocks public access, encrypts data, enables versioning, denies non-TLS requests and refuses automatic destruction. Publisher, verifier and topic-admin IAM policies are separate; no workload identity/role attachment is invented here. Object permissions target only `normalized/v1/*`, while bucket-scoped listing supports readiness/missing-key checks. Future workload IAM, SDK/token renewal and cross-service network access remain unverified. Versioned objects and retained buckets can keep charging after a demonstration; teardown needs separate approval and a complete cost review.
