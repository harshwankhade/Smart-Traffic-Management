# Phase 8 integrated acceptance checkpoint — 2026-11-15

The authorized integrated run reached a healthy GitOps state at commit `280fc39`: all
six Kubernetes services, both Event Publisher replicas, and the three-node ZooKeeper
quorum were ready. The constrained runtime used two EKS `t3.large` workers and one
single-node EMR `m5.xlarge` cluster, remaining within the account's eight-vCPU quota.

One unique in-cluster REST reading was accepted by Traffic Ingestion and archived in
S3. A subsequent watermark-advancing reading produced a Kafka/EMR Flink result that
Traffic Analytics persisted and Signal Recommendation converted into a simulated
high-congestion green-extension recommendation. An Incident Manager collision event
entered SQS, was consumed by Lambda, and was recorded in the alerts DynamoDB table.

ZooKeeper failover was exercised by deleting the elected Event Publisher pod. The
connected follower became the elected leader and Traffic Ingestion remained ready.
Signal Recommendation later exposed a missing scoped SQS permission for congestion
alerts; Terraform attached the existing queue-specific policy, the consumer was
restarted, and the service returned ready.

Route 53 resolves `api.smarttrafficmgmt.online`, and the ALB listener uses the issued
regional ACM certificate. Automated public HTTPS verification from this workstation
remains unverified because its outbound TLS path injects an untrusted self-signed
certificate; verification was not weakened. All private application and storage paths
above were observed live. Teardown/audit follows this checkpoint.
