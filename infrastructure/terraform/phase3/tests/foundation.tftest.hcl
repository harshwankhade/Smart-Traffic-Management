mock_provider "aws" {
  mock_resource "aws_msk_cluster" {
    defaults = { arn = "arn:aws:kafka:ap-south-1:123456789012:cluster/test/uuid" }
  }
  mock_resource "aws_s3_bucket" {
    defaults = { arn = "arn:aws:s3:::mock-archive", id = "mock-archive" }
  }
}

variables {
  vpc_id                        = "vpc-mocked"
  private_subnet_ids            = ["subnet-mock-a", "subnet-mock-b"]
  private_route_table_ids       = ["rtb-mock"]
  application_security_group_id = "sg-mock-application"
}

run "deployment_denied_by_default" {
  command         = plan
  expect_failures = [terraform_data.deployment_guard]
}

run "private_kafka_archive" {
  command = plan
  variables {
    deployment_approved = true # Mock provider only; no actual approval or AWS calls.
  }
  assert {
    condition = (
      aws_msk_cluster.main.number_of_broker_nodes == 2 &&
      aws_msk_cluster.main.kafka_version == "3.9.x" &&
      one(aws_msk_cluster.main.broker_node_group_info).instance_type == "kafka.t3.small" &&
      one(one(one(aws_msk_cluster.main.broker_node_group_info).storage_info).ebs_storage_info).volume_size == 10 &&
      one(one(aws_msk_cluster.main.encryption_info).encryption_in_transit).client_broker == "TLS" &&
      one(one(aws_msk_cluster.main.client_authentication).sasl).iam &&
      !one(aws_msk_cluster.main.client_authentication).unauthenticated &&
      aws_msk_topic.raw.replication_factor == 2 && aws_msk_topic.raw.partition_count == 1 &&
      jsondecode(aws_msk_topic.raw.configs)["min.insync.replicas"] == "2"
    )
    error_message = "Kafka must match the approved small two-broker configuration."
  }
  assert {
    condition = (
      !aws_s3_bucket.archive.force_destroy &&
      aws_s3_bucket_public_access_block.archive.block_public_acls &&
      aws_s3_bucket_public_access_block.archive.block_public_policy &&
      aws_s3_bucket_public_access_block.archive.ignore_public_acls &&
      aws_s3_bucket_public_access_block.archive.restrict_public_buckets &&
      one(one(aws_s3_bucket_server_side_encryption_configuration.archive.rule).apply_server_side_encryption_by_default).sse_algorithm == "AES256" &&
      one(aws_s3_bucket_versioning.archive.versioning_configuration).status == "Enabled" &&
      aws_vpc_security_group_ingress_rule.application_kafka.from_port == 9098 &&
      aws_vpc_security_group_ingress_rule.application_kafka.referenced_security_group_id == var.application_security_group_id
    )
    error_message = "Private storage and IAM-TLS Kafka access must be preserved."
  }
}
