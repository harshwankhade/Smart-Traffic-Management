resource "terraform_data" "deployment_guard" {
  lifecycle {
    precondition {
      condition     = var.deployment_approved
      error_message = "Managed DynamoDB provisioning requires explicit approval and a reviewed cost/access preflight."
    }
  }
}

locals {
  recommendations_table = "${var.project_name}-recommendations"
  summaries_table       = "${var.project_name}-summaries"
  common_tags = {
    Project = "SmartTraffic"
    Phase   = "5"
    Purpose = "TemporaryDynamoDBVerification"
  }
}

resource "aws_dynamodb_table" "recommendations" {
  name         = local.recommendations_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "intersection_id"
  range_key    = "window_key"
  table_class  = "STANDARD"

  attribute {
    name = "intersection_id"
    type = "S"
  }

  attribute {
    name = "window_key"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  tags       = merge(local.common_tags, { Owner = "SignalRecommendation" })
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_dynamodb_table" "summaries" {
  name         = local.summaries_table
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "intersection_id"
  range_key    = "window_key"
  table_class  = "STANDARD"

  attribute {
    name = "intersection_id"
    type = "S"
  }

  attribute {
    name = "window_key"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  tags       = merge(local.common_tags, { Owner = "TrafficAnalytics" })
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_iam_policy" "signal_recommendation" {
  name = "${var.project_name}-signal-recommendation-dynamodb"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
      Resource = aws_dynamodb_table.recommendations.arn
    }]
  })
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_iam_policy" "traffic_analytics" {
  name = "${var.project_name}-traffic-analytics-dynamodb"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]
      Resource = aws_dynamodb_table.summaries.arn
    }]
  })
  depends_on = [terraform_data.deployment_guard]
}
