mock_provider "aws" {
  mock_resource "aws_security_group" {
    defaults        = { id = "sg-mock" }
    override_during = plan
  }
  mock_resource "aws_iam_role" {
    defaults        = { arn = "arn:aws:iam::123456789012:role/mock", id = "mock-role", name = "mock-role" }
    override_during = plan
  }
  mock_resource "aws_iam_instance_profile" {
    defaults        = { arn = "arn:aws:iam::123456789012:instance-profile/mock" }
    override_during = plan
  }
  mock_resource "aws_emr_cluster" {
    defaults        = { id = "j-MOCK", name = "mock-emr" }
    override_during = plan
  }
}

variables {
  vpc_id                  = "vpc-mock"
  private_subnet_ids      = ["subnet-a", "subnet-b"]
  kafka_cluster_arn       = "arn:aws:kafka:ap-south-1:123456789012:cluster/mock/uuid"
  kafka_security_group_id = "sg-kafka"
  kafka_bootstrap_servers = "mock:9098"
  s3_prefix_list_id       = "pl-mock"
  archive_bucket          = "mock-archive"
}

run "deployment_denied_by_default" {
  command         = plan
  expect_failures = [terraform_data.deployment_guard]
}

run "emr_flink_configuration" {
  command = plan
  variables { deployment_approved = true }
  assert {
    condition     = aws_emr_cluster.congestion.release_label == "emr-7.14.0" && contains(aws_emr_cluster.congestion.applications, "Flink")
    error_message = "Use the approved EMR 7.14 Flink managed cluster."
  }
  assert {
    condition     = aws_emr_cluster.congestion.master_instance_group[0].instance_count == 1 && aws_emr_cluster.congestion.core_instance_group[0].instance_count == 1
    error_message = "The temporary managed test needs exactly one primary and one core node."
  }
  assert {
    condition     = aws_msk_topic.results.name == "traffic.results" && aws_msk_topic.results.replication_factor == 2 && jsondecode(aws_msk_topic.results.configs)["min.insync.replicas"] == "2"
    error_message = "Results must use the distinct two-replica Kafka topic."
  }
  assert {
    condition = (
      aws_vpc_security_group_egress_rule.primary_kafka.to_port == 9098 &&
      aws_vpc_security_group_egress_rule.core_s3.to_port == 443 &&
      aws_vpc_security_group_ingress_rule.service_from_primary.to_port == 9443 &&
      aws_vpc_security_group_ingress_rule.primary_from_service.to_port == 8443 &&
      aws_vpc_security_group_ingress_rule.core_from_service.to_port == 8443
    )
    error_message = "EMR nodes need private data-plane and EMR 7.x control-plane rules."
  }
  assert {
    condition     = aws_s3_object.jar.key == "artifacts/congestion-processor-1.0.0-emr.jar"
    error_message = "Deploy the isolated Flink 1.20 EMR artifact."
  }
  assert {
    condition = (
      jsondecode(aws_iam_role_policy.emr_service_pass_ec2_role.policy).Statement[0].Action == "iam:PassRole" &&
      jsondecode(aws_iam_role_policy.emr_service_pass_ec2_role.policy).Statement[0].Resource == aws_iam_role.emr_ec2.arn &&
      jsondecode(aws_iam_role_policy.emr_service_pass_ec2_role.policy).Statement[0].Condition.StringEquals["iam:PassedToService"] == "ec2.amazonaws.com"
    )
    error_message = "The EMR service role may pass only this stack's EC2 role to EC2."
  }
  assert {
    condition = (
      aws_security_group.emr_primary.revoke_rules_on_delete &&
      aws_security_group.emr_core.revoke_rules_on_delete &&
      aws_security_group.emr_service.revoke_rules_on_delete
    )
    error_message = "All state-owned EMR security groups must revoke EMR-added rules before deletion."
  }
}
