output "kafka_bootstrap_servers" {
  value = aws_msk_cluster.main.bootstrap_brokers_sasl_iam
}
output "kafka_cluster_arn" {
  value = aws_msk_cluster.main.arn
}
output "kafka_security_group_id" {
  value = aws_security_group.kafka.id
}
output "s3_prefix_list_id" {
  value = aws_vpc_endpoint.s3.prefix_list_id
}
output "archive_bucket" {
  value = aws_s3_bucket.archive.id
}
output "publisher_policy_arn" {
  value = aws_iam_policy.publisher.arn
}
output "verification_policy_arn" {
  value = aws_iam_policy.verifier.arn
}
