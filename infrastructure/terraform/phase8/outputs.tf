output "eks_cluster_name" { value = aws_eks_cluster.main.name }
output "ecr_repositories" { value = { for name, repo in data.aws_ecr_repository.services : name => repo.repository_url } }
output "kafka_bootstrap_servers" { value = "kafka.smarttraffic.internal:9093" }
output "archive_bucket" { value = aws_s3_bucket.archive.id }
output "emr_cluster_id" { value = module.processing.emr_cluster_id }
output "flink_artifact_uri" { value = "s3://${aws_s3_bucket.archive.id}/${module.processing.artifact_key}" }
output "kafka_ca_uri" { value = "s3://${aws_s3_bucket.archive.id}/${aws_s3_object.kafka_ca.key}" }
output "rds_endpoint" { value = aws_db_instance.main.address }
output "public_https_dns_name" { value = var.public_dns_name }
output "alert_queue_url" { value = module.alerts.alert_queue_url }
