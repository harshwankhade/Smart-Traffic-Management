resource "terraform_data" "deployment_guard" {
  lifecycle {
    precondition {
      condition     = var.deployment_approved
      error_message = "Phase 3 permits validation and mocked tests only. No cloud spending is authorized."
    }
  }
}

resource "aws_security_group" "kafka" {
  name_prefix = "${var.project_name}-kafka-"
  vpc_id      = var.vpc_id
  depends_on  = [terraform_data.deployment_guard]
}

resource "aws_vpc_security_group_ingress_rule" "application_kafka" {
  security_group_id            = aws_security_group.kafka.id
  referenced_security_group_id = var.application_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 9098
  to_port                      = 9098
}

resource "aws_vpc_security_group_ingress_rule" "broker_traffic" {
  security_group_id            = aws_security_group.kafka.id
  referenced_security_group_id = aws_security_group.kafka.id
  ip_protocol                  = "tcp"
  from_port                    = 0
  to_port                      = 65535
}

resource "aws_vpc_security_group_egress_rule" "broker_traffic" {
  security_group_id            = aws_security_group.kafka.id
  referenced_security_group_id = aws_security_group.kafka.id
  ip_protocol                  = "tcp"
  from_port                    = 0
  to_port                      = 65535
}

resource "aws_vpc_security_group_egress_rule" "application_kafka" {
  security_group_id            = var.application_security_group_id
  referenced_security_group_id = aws_security_group.kafka.id
  ip_protocol                  = "tcp"
  from_port                    = 9098
  to_port                      = 9098
}

resource "aws_msk_configuration" "main" {
  name              = var.project_name
  kafka_versions    = ["3.9.x"]
  server_properties = <<-PROPERTIES
    auto.create.topics.enable=false
    default.replication.factor=2
    min.insync.replicas=2
    offsets.topic.replication.factor=2
    log.retention.hours=24
  PROPERTIES
}

resource "aws_msk_cluster" "main" {
  cluster_name           = var.project_name
  kafka_version          = "3.9.x"
  number_of_broker_nodes = 2
  broker_node_group_info {
    instance_type   = "kafka.t3.small"
    client_subnets  = var.private_subnet_ids
    security_groups = [aws_security_group.kafka.id]
    connectivity_info {
      public_access {
        type = "DISABLED"
      }
    }
    storage_info {
      ebs_storage_info {
        volume_size = 10
      }
    }
  }
  client_authentication {
    sasl {
      iam = true
    }
    unauthenticated = false
  }
  encryption_info {
    encryption_in_transit {
      client_broker = "TLS"
      in_cluster    = true
    }
  }
  configuration_info {
    arn      = aws_msk_configuration.main.arn
    revision = aws_msk_configuration.main.latest_revision
  }
}

resource "aws_msk_topic" "raw" {
  cluster_arn        = aws_msk_cluster.main.arn
  name               = "traffic.raw"
  partition_count    = 1
  replication_factor = 2
  configs = jsonencode({
    "retention.ms"        = "86400000"
    "cleanup.policy"      = "delete"
    "min.insync.replicas" = "2"
  })
}

resource "aws_s3_bucket" "archive" {
  bucket_prefix = "${var.project_name}-"
  force_destroy = false
  depends_on    = [terraform_data.deployment_guard]
}

resource "aws_s3_bucket_public_access_block" "archive" {
  bucket                  = aws_s3_bucket.archive.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "archive" {
  bucket = aws_s3_bucket.archive.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "archive" {
  bucket = aws_s3_bucket.archive.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_policy" "archive" {
  bucket = aws_s3_bucket.archive.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyNonTLS", Effect = "Deny", Principal = "*", Action = "s3:*",
      Resource  = [aws_s3_bucket.archive.arn, "${aws_s3_bucket.archive.arn}/*"],
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })
}

resource "aws_vpc_endpoint" "s3" {
  vpc_id            = var.vpc_id
  service_name      = "com.amazonaws.ap-south-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = var.private_route_table_ids
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { Effect = "Allow", Principal = "*", Action = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:ListBucket", "s3:AbortMultipartUpload"], Resource = [aws_s3_bucket.archive.arn, "${aws_s3_bucket.archive.arn}/*"] },
      { Effect = "Allow", Principal = "*", Action = ["s3:GetObject"], Resource = ["arn:aws:s3:::al2023-repos-ap-south-1-de612dc2/*", "arn:aws:s3:::repo.ap-south-1.emr.amazonaws.com/*"] },
      { Effect = "Allow", Principal = "*", Action = ["s3:PutObject"], Resource = "arn:aws:s3:::aws157-logs-prod-ap-south-1/*" }
    ]
  })
}

resource "aws_vpc_security_group_egress_rule" "application_s3" {
  security_group_id = var.application_security_group_id
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}

locals {
  topic_arn = replace(aws_msk_cluster.main.arn, ":cluster/", ":topic/")
  group_arn = replace(aws_msk_cluster.main.arn, ":cluster/", ":group/")
}

resource "aws_iam_policy" "publisher" {
  name_prefix = "${var.project_name}-publisher-"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["kafka-cluster:Connect", "kafka-cluster:WriteDataIdempotently"], Resource = aws_msk_cluster.main.arn },
      { Effect = "Allow", Action = ["kafka-cluster:DescribeTopic", "kafka-cluster:WriteData"], Resource = "${local.topic_arn}/traffic.raw" },
      { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.archive.arn}/normalized/v1/*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.archive.arn }
    ]
  })
}

resource "aws_iam_policy" "verifier" {
  name_prefix = "${var.project_name}-verifier-"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["kafka-cluster:Connect"], Resource = aws_msk_cluster.main.arn },
      { Effect = "Allow", Action = ["kafka-cluster:DescribeTopic", "kafka-cluster:ReadData"], Resource = "${local.topic_arn}/traffic.raw" },
      { Effect = "Allow", Action = ["kafka-cluster:DescribeGroup", "kafka-cluster:AlterGroup"], Resource = "${local.group_arn}/phase3-verifier-*" },
      { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${aws_s3_bucket.archive.arn}/normalized/v1/*" },
      { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.archive.arn }
    ]
  })
}

resource "aws_iam_policy" "topic_admin" {
  name_prefix = "${var.project_name}-topic-admin-"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      { Effect = "Allow", Action = ["kafka:CreateTopic", "kafka:DescribeTopic", "kafka:UpdateTopic", "kafka:DeleteTopic"], Resource = aws_msk_cluster.main.arn },
      { Effect = "Allow", Action = ["kafka-cluster:Connect"], Resource = aws_msk_cluster.main.arn },
      { Effect = "Allow", Action = ["kafka-cluster:CreateTopic", "kafka-cluster:DescribeTopic", "kafka-cluster:AlterTopic", "kafka-cluster:AlterTopicDynamicConfiguration"], Resource = "${local.topic_arn}/traffic.raw" }
    ]
  })
}
