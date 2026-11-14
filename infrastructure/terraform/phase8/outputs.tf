output "eks_cluster_name" { value = aws_eks_cluster.main.name }
output "ecr_repositories" { value = { for name, repo in aws_ecr_repository.services : name => repo.repository_url } }
output "kafka_bootstrap_servers" { value = module.streaming.kafka_bootstrap_servers }
output "archive_bucket" { value = module.streaming.archive_bucket }
output "rds_endpoint" { value = aws_db_instance.main.address }
output "public_https_dns_name" { value = var.public_dns_name }
output "alert_queue_url" { value = module.alerts.alert_queue_url }
