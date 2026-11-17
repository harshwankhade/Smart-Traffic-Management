resource "terraform_data" "deployment_guard" {
  lifecycle {
    precondition {
      condition     = var.deployment_approved
      error_message = "EMR provisioning requires explicit approval. The default permits mocked tests and validation only."
    }
  }
}

locals {
  topic_prefix      = replace(var.kafka_cluster_arn, ":cluster/", ":topic/")
  group_prefix      = replace(var.kafka_cluster_arn, ":cluster/", ":group/")
  artifact_key      = "artifacts/congestion-processor-1.0.0-emr.jar"
  emr_log_agent_key = "artifacts/emr-cloudwatch-agent.sh"
  emr_tag           = { "for-use-with-amazon-emr-managed-policies" = "true" }
}

resource "aws_msk_topic" "results" {
  cluster_arn        = var.kafka_cluster_arn
  name               = "traffic.results"
  partition_count    = 1
  replication_factor = 2
  configs            = jsonencode({ "retention.ms" = "86400000", "cleanup.policy" = "delete", "min.insync.replicas" = "2" })
  depends_on         = [terraform_data.deployment_guard]
}

resource "aws_s3_object" "jar" {
  bucket                 = var.archive_bucket
  key                    = local.artifact_key
  source                 = var.jar_path
  etag                   = filemd5(var.jar_path)
  server_side_encryption = "AES256"
  depends_on             = [terraform_data.deployment_guard]
}
resource "aws_s3_object" "emr_log_agent" {
  bucket                 = var.archive_bucket
  key                    = local.emr_log_agent_key
  source                 = "${path.module}/assets/emr-cloudwatch-agent.sh"
  etag                   = filemd5("${path.module}/assets/emr-cloudwatch-agent.sh")
  server_side_encryption = "AES256"
  depends_on             = [terraform_data.deployment_guard]
}
resource "aws_s3_object" "flink_log_agent_config" {
  bucket                 = var.archive_bucket
  key                    = "artifacts/phase9-flink-cloudwatch-agent.json"
  source                 = "${path.module}/assets/flink-cloudwatch-agent.json"
  etag                   = filemd5("${path.module}/assets/flink-cloudwatch-agent.json")
  server_side_encryption = "AES256"
  depends_on             = [terraform_data.deployment_guard]
}
resource "aws_s3_object" "flink_log_agent_installer" {
  bucket                 = var.archive_bucket
  key                    = "artifacts/install-phase9-flink-cloudwatch-agent.sh"
  source                 = "${path.module}/assets/install-flink-cloudwatch-agent.sh"
  etag                   = filemd5("${path.module}/assets/install-flink-cloudwatch-agent.sh")
  server_side_encryption = "AES256"
  depends_on             = [terraform_data.deployment_guard]
}
resource "aws_cloudwatch_log_group" "emr" {
  name              = "/smarttraffic/${var.project_name}/emr"
  retention_in_days = 7
  depends_on        = [terraform_data.deployment_guard]
}

resource "aws_security_group" "emr_primary" {
  name_prefix            = "${var.project_name}-primary-"
  description            = "EMR primary node for temporary Phase 4 verification"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  tags                   = local.emr_tag
  depends_on             = [terraform_data.deployment_guard]
}

resource "aws_security_group" "emr_core" {
  name_prefix            = "${var.project_name}-core-"
  description            = "EMR core node for temporary Phase 4 verification"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  tags                   = local.emr_tag
  depends_on             = [terraform_data.deployment_guard]
}

resource "aws_security_group" "emr_service" {
  name_prefix            = "${var.project_name}-service-"
  description            = "EMR service access in the isolated subnet"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  tags                   = local.emr_tag
  depends_on             = [terraform_data.deployment_guard]
}

# The interface endpoint itself is owned by the Phase 8 VPC.  Keeping its
# security group in this module avoids a dependency cycle: the endpoint must
# allow the EMR primary group, while the primary group must allow the endpoint.
resource "aws_security_group" "cloudwatch_logs_endpoint" {
  name_prefix            = "${var.project_name}-logs-endpoint-"
  description            = "CloudWatch Logs interface endpoint access from the EMR primary node"
  vpc_id                 = var.vpc_id
  revoke_rules_on_delete = true
  tags                   = local.emr_tag
  depends_on             = [terraform_data.deployment_guard]
}

# EMR 7.x adds required inbound rules to custom managed groups. These explicit
# outbound rules are the minimum that EMR does not add for custom groups.
resource "aws_vpc_security_group_egress_rule" "primary_core" {
  security_group_id            = aws_security_group.emr_primary.id
  referenced_security_group_id = aws_security_group.emr_core.id
  ip_protocol                  = "-1"
}
resource "aws_vpc_security_group_egress_rule" "core_primary" {
  security_group_id            = aws_security_group.emr_core.id
  referenced_security_group_id = aws_security_group.emr_primary.id
  ip_protocol                  = "-1"
}
resource "aws_vpc_security_group_egress_rule" "primary_self" {
  security_group_id            = aws_security_group.emr_primary.id
  referenced_security_group_id = aws_security_group.emr_primary.id
  ip_protocol                  = "-1"
}
resource "aws_vpc_security_group_egress_rule" "core_self" {
  security_group_id            = aws_security_group.emr_core.id
  referenced_security_group_id = aws_security_group.emr_core.id
  ip_protocol                  = "-1"
}
resource "aws_vpc_security_group_egress_rule" "primary_service" {
  security_group_id            = aws_security_group.emr_primary.id
  referenced_security_group_id = aws_security_group.emr_service.id
  ip_protocol                  = "tcp"
  from_port                    = 9443
  to_port                      = 9443
}
resource "aws_vpc_security_group_egress_rule" "primary_cloudwatch_logs_endpoint" {
  security_group_id            = aws_security_group.emr_primary.id
  referenced_security_group_id = aws_security_group.cloudwatch_logs_endpoint.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
resource "aws_vpc_security_group_ingress_rule" "cloudwatch_logs_endpoint_from_primary" {
  security_group_id            = aws_security_group.cloudwatch_logs_endpoint.id
  referenced_security_group_id = aws_security_group.emr_primary.id
  ip_protocol                  = "tcp"
  from_port                    = 443
  to_port                      = 443
}
resource "aws_vpc_security_group_egress_rule" "service_primary" {
  security_group_id            = aws_security_group.emr_service.id
  referenced_security_group_id = aws_security_group.emr_primary.id
  ip_protocol                  = "tcp"
  from_port                    = 8443
  to_port                      = 8443
}
resource "aws_vpc_security_group_egress_rule" "service_core" {
  security_group_id            = aws_security_group.emr_service.id
  referenced_security_group_id = aws_security_group.emr_core.id
  ip_protocol                  = "tcp"
  from_port                    = 8443
  to_port                      = 8443
}
resource "aws_vpc_security_group_ingress_rule" "service_from_primary" {
  security_group_id            = aws_security_group.emr_service.id
  referenced_security_group_id = aws_security_group.emr_primary.id
  ip_protocol                  = "tcp"
  from_port                    = 9443
  to_port                      = 9443
}
resource "aws_vpc_security_group_ingress_rule" "primary_from_service" {
  security_group_id            = aws_security_group.emr_primary.id
  referenced_security_group_id = aws_security_group.emr_service.id
  ip_protocol                  = "tcp"
  from_port                    = 8443
  to_port                      = 8443
}
resource "aws_vpc_security_group_ingress_rule" "core_from_service" {
  security_group_id            = aws_security_group.emr_core.id
  referenced_security_group_id = aws_security_group.emr_service.id
  ip_protocol                  = "tcp"
  from_port                    = 8443
  to_port                      = 8443
}
resource "aws_vpc_security_group_ingress_rule" "primary_cluster" {
  for_each                     = { primary = aws_security_group.emr_primary.id, core = aws_security_group.emr_core.id }
  security_group_id            = aws_security_group.emr_primary.id
  referenced_security_group_id = each.value
  ip_protocol                  = "-1"
}
resource "aws_vpc_security_group_ingress_rule" "core_cluster" {
  for_each                     = { primary = aws_security_group.emr_primary.id, core = aws_security_group.emr_core.id }
  security_group_id            = aws_security_group.emr_core.id
  referenced_security_group_id = each.value
  ip_protocol                  = "-1"
}
resource "aws_vpc_security_group_egress_rule" "primary_s3" {
  security_group_id = aws_security_group.emr_primary.id
  prefix_list_id    = var.s3_prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_vpc_security_group_egress_rule" "core_s3" {
  security_group_id = aws_security_group.emr_core.id
  prefix_list_id    = var.s3_prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}
resource "aws_vpc_security_group_egress_rule" "primary_kafka" {
  security_group_id            = aws_security_group.emr_primary.id
  referenced_security_group_id = var.kafka_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 9098
  to_port                      = 9098
}
resource "aws_vpc_security_group_egress_rule" "core_kafka" {
  security_group_id            = aws_security_group.emr_core.id
  referenced_security_group_id = var.kafka_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 9098
  to_port                      = 9098
}
resource "aws_vpc_security_group_ingress_rule" "emr_kafka" {
  for_each                     = { primary = aws_security_group.emr_primary.id, core = aws_security_group.emr_core.id }
  security_group_id            = var.kafka_security_group_id
  referenced_security_group_id = each.value
  ip_protocol                  = "tcp"
  from_port                    = 9098
  to_port                      = 9098
}

resource "aws_iam_role" "emr_service" {
  name_prefix = "${var.project_name}-service-"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "elasticmapreduce.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  depends_on = [terraform_data.deployment_guard]
}
resource "aws_iam_role_policy_attachment" "emr_service" {
  role       = aws_iam_role.emr_service.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonEMRServicePolicy_v2"
}
resource "aws_iam_role" "emr_ec2" {
  name = "${var.project_name}-ec2"
  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [{ Effect = "Allow", Principal = { Service = "ec2.amazonaws.com" }, Action = "sts:AssumeRole" }]
  })
  depends_on = [terraform_data.deployment_guard]
}
resource "aws_iam_role_policy" "emr_service_pass_ec2_role" {
  name = "pass-emr-ec2-role"
  role = aws_iam_role.emr_service.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "iam:PassRole"
      Resource = aws_iam_role.emr_ec2.arn
      Condition = {
        StringEquals = { "iam:PassedToService" = "ec2.amazonaws.com" }
      }
    }]
  })
}
resource "aws_iam_instance_profile" "emr_ec2" {
  name = aws_iam_role.emr_ec2.name
  role = aws_iam_role.emr_ec2.name
}
resource "aws_iam_role_policy" "emr_ec2" {
  role = aws_iam_role.emr_ec2.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:AbortMultipartUpload"], Resource = "arn:aws:s3:::${var.archive_bucket}/*" },
      { Effect = "Allow", Action = ["s3:GetBucketLocation", "s3:ListBucket", "s3:ListBucketMultipartUploads"], Resource = "arn:aws:s3:::${var.archive_bucket}" },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = ["arn:aws:s3:::al2023-repos-ap-south-1-de612dc2/*", "arn:aws:s3:::repo.ap-south-1.emr.amazonaws.com/*"] },
      { Effect = "Allow", Action = ["kafka-cluster:Connect", "kafka-cluster:DescribeCluster", "kafka-cluster:WriteDataIdempotently"], Resource = var.kafka_cluster_arn },
      { Effect = "Allow", Action = ["kafka-cluster:DescribeTopic", "kafka-cluster:ReadData", "kafka-cluster:WriteData"], Resource = ["${local.topic_prefix}/traffic.raw", "${local.topic_prefix}/traffic.results"] },
      { Effect = "Allow", Action = ["kafka-cluster:DescribeGroup", "kafka-cluster:AlterGroup"], Resource = ["${local.group_prefix}/congestion-v1", "${local.group_prefix}/congestion-verification-v1"] },
      { Effect = "Allow", Action = ["elasticmapreduce:DescribeCluster", "elasticmapreduce:ListInstances"], Resource = "*" },
      { Effect = "Allow", Action = ["logs:DescribeLogGroups"], Resource = "*" },
      { Effect = "Allow", Action = ["logs:CreateLogGroup"], Resource = "*" },
      { Effect = "Allow", Action = ["logs:PutRetentionPolicy"], Resource = aws_cloudwatch_log_group.emr.arn },
      { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:DescribeLogStreams", "logs:PutLogEvents"], Resource = "${aws_cloudwatch_log_group.emr.arn}:*" }
    ]
  })
}

locals {
  # The AWS provider schema at 6.45 does not expose EMR's creation-time
  # MonitoringConfiguration.  CloudFormation does, so Terraform owns this
  # stack and still records the cluster in the same root state.
  emr_native_cloudwatch_template = jsonencode({
    AWSTemplateFormatVersion = "2010-09-09"
    Resources = {
      CongestionCluster = {
        Type = "AWS::EMR::Cluster"
        Properties = {
          Name         = var.project_name
          ReleaseLabel = "emr-7.14.0"
          Applications = [{ Name = "Flink" }, { Name = "AmazonCloudWatchAgent" }]
          ServiceRole  = aws_iam_role.emr_service.arn
          JobFlowRole  = aws_iam_instance_profile.emr_ec2.name
          LogUri       = "s3://${var.archive_bucket}/emr-logs/"
          Instances = {
            Ec2SubnetId                   = var.private_subnet_ids[0]
            EmrManagedMasterSecurityGroup = aws_security_group.emr_primary.id
            EmrManagedSlaveSecurityGroup  = aws_security_group.emr_core.id
            ServiceAccessSecurityGroup    = aws_security_group.emr_service.id
            KeepJobFlowAliveWhenNoSteps   = true
            TerminationProtected          = false
            MasterInstanceGroup = {
              Name          = "Primary"
              InstanceType  = var.emr_instance_type
              InstanceCount = 1
            }
          }
          AutoTerminationPolicy = { IdleTimeout = 14400 }
          StepConcurrencyLevel  = 1
          MonitoringConfiguration = {
            CloudWatchLogConfiguration = {
              Enabled             = true
              LogGroupName        = aws_cloudwatch_log_group.emr.name
              LogStreamNamePrefix = "phase9"
              LogTypes = {
                STEP_LOGS      = ["STDOUT", "STDERR"]
                SPARK_DRIVER   = ["STDOUT", "STDERR"]
                SPARK_EXECUTOR = ["STDOUT", "STDERR"]
              }
            }
          }
          Tags = [for key, value in merge(local.emr_tag, { Project = "SmartTraffic", Purpose = "Phase4TemporaryVerification" }) : { Key = key, Value = value }]
        }
      }
    }
    Outputs = {
      ClusterId   = { Value = { Ref = "CongestionCluster" } }
      ClusterName = { Value = var.project_name }
    }
  })
}

resource "aws_cloudformation_stack" "congestion" {
  name          = "${var.project_name}-native-cloudwatch"
  template_body = local.emr_native_cloudwatch_template
  on_failure    = "DELETE"
  tags          = merge(local.emr_tag, { Project = "SmartTraffic", Purpose = "Phase4TemporaryVerification" })

  depends_on = [
    aws_iam_role_policy_attachment.emr_service,
    aws_iam_role_policy.emr_service_pass_ec2_role,
    aws_iam_role_policy.emr_ec2,
    aws_cloudwatch_log_group.emr,
    aws_msk_topic.results,
    aws_vpc_security_group_ingress_rule.emr_kafka,
    aws_vpc_security_group_egress_rule.primary_service,
    aws_vpc_security_group_egress_rule.service_primary,
    aws_vpc_security_group_egress_rule.service_core,
    aws_vpc_security_group_ingress_rule.service_from_primary,
    aws_vpc_security_group_ingress_rule.primary_from_service,
    aws_vpc_security_group_ingress_rule.core_from_service
  ]
}
