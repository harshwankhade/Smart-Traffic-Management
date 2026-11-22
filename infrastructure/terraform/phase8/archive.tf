resource "aws_s3_bucket" "archive" {
  # Preserve the former module.streaming prefix when adopting existing state.
  bucket_prefix = "${var.project_name}-kafka-"
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
  vpc_id            = aws_vpc.main.id
  service_name      = "com.amazonaws.ap-south-1.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [aws_route_table.private.id]
  policy = jsonencode({
    Version = "2012-10-17",
    Statement = [
      { Effect = "Allow", Principal = "*", Action = ["s3:GetObject", "s3:GetObjectVersion", "s3:PutObject", "s3:ListBucket", "s3:AbortMultipartUpload"], Resource = [aws_s3_bucket.archive.arn, "${aws_s3_bucket.archive.arn}/*"] },
      { Effect = "Allow", Principal = "*", Action = ["s3:GetObject"], Resource = ["arn:aws:s3:::al2023-repos-ap-south-1-de612dc2/*", "arn:aws:s3:::repo.ap-south-1.emr.amazonaws.com/*"] },
      { Effect = "Allow", Principal = "*", Action = ["s3:GetObject"], Resource = "arn:aws:s3:::prod-ap-south-1-starport-layer-bucket/*" },
      { Effect = "Allow", Principal = "*", Action = ["s3:GetObject"], Resource = "arn:aws:s3:::prod-registry-k8s-io-ap-south-1/*" },
      { Effect = "Allow", Principal = "*", Action = ["s3:PutObject"], Resource = "arn:aws:s3:::aws157-logs-prod-ap-south-1/*" }
    ]
  })
}

resource "aws_vpc_security_group_egress_rule" "application_s3" {
  security_group_id = aws_eks_cluster.main.vpc_config[0].cluster_security_group_id
  prefix_list_id    = aws_vpc_endpoint.s3.prefix_list_id
  ip_protocol       = "tcp"
  from_port         = 443
  to_port           = 443
}


resource "aws_iam_policy" "publisher_archive" {
  name_prefix = "${var.project_name}-archive-"
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject"], Resource = "${aws_s3_bucket.archive.arn}/normalized/v1/*" },
    { Effect = "Allow", Action = ["s3:ListBucket"], Resource = aws_s3_bucket.archive.arn }
  ] })
}
