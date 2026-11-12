resource "terraform_data" "deployment_guard" {
  lifecycle {
    precondition {
      condition     = var.deployment_approved
      error_message = "Phase 6 cloud creation requires explicit approval and a reviewed full-lifecycle cost estimate."
    }
  }
}

locals {
  alert_queue_name = "${var.project_name}-alerts"
  dlq_name         = "${var.project_name}-alerts-dlq"
  function_name    = "${var.project_name}-alert-service"
  common_tags = {
    Project = "SmartTraffic"
    Phase   = "6"
    Purpose = "TemporaryAlertVerification"
  }
}

resource "aws_sqs_queue" "dlq" {
  name                      = local.dlq_name
  message_retention_seconds = 345600
  sqs_managed_sse_enabled   = true
  tags                      = local.common_tags
  depends_on                = [terraform_data.deployment_guard]
}

resource "aws_sqs_queue" "alerts" {
  name                       = local.alert_queue_name
  visibility_timeout_seconds = 60
  message_retention_seconds  = 86400
  sqs_managed_sse_enabled    = true
  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.dlq.arn
    maxReceiveCount     = 5
  })
  tags       = local.common_tags
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_dynamodb_table" "alerts" {
  name         = "${var.project_name}-alerts"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "alert_id"
  table_class  = "STANDARD"

  attribute {
    name = "alert_id"
    type = "S"
  }

  server_side_encryption {
    enabled = true
  }

  tags       = merge(local.common_tags, { Owner = "AlertService" })
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_cloudwatch_log_group" "alerts" {
  name              = "/aws/lambda/${local.function_name}"
  retention_in_days = 7
  tags              = local.common_tags
  depends_on        = [terraform_data.deployment_guard]
}

resource "aws_iam_role" "lambda" {
  name = "${var.project_name}-alert-lambda"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Action    = "sts:AssumeRole"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })
  tags       = local.common_tags
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_iam_role_policy" "lambda" {
  name = "${var.project_name}-alert-runtime"
  role = aws_iam_role.lambda.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]
        Resource = aws_sqs_queue.alerts.arn
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:PutItem", "dynamodb:GetItem"]
        Resource = aws_dynamodb_table.alerts.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.alerts.arn}:*"
      }
    ]
  })
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_iam_policy" "signal_recommendation_send" {
  name = "${var.project_name}-signal-alert-send"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = aws_sqs_queue.alerts.arn
    }]
  })
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_iam_policy" "incident_manager_send" {
  name = "${var.project_name}-incident-alert-send"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = ["sqs:SendMessage"]
      Resource = aws_sqs_queue.alerts.arn
    }]
  })
  depends_on = [terraform_data.deployment_guard]
}

resource "aws_lambda_function" "alerts" {
  function_name    = local.function_name
  role             = aws_iam_role.lambda.arn
  runtime          = "python3.14"
  handler          = "handler.handler"
  filename         = abspath("${path.module}/${var.lambda_zip_path}")
  source_code_hash = filebase64sha256("${path.module}/${var.lambda_zip_path}")
  timeout          = 10
  memory_size      = 128

  environment {
    variables = {
      ALERTS_TABLE = aws_dynamodb_table.alerts.name
    }
  }

  tags = local.common_tags
  depends_on = [aws_cloudwatch_log_group.alerts, aws_iam_role_policy.lambda,
  terraform_data.deployment_guard]
}

resource "aws_lambda_event_source_mapping" "alerts" {
  event_source_arn        = aws_sqs_queue.alerts.arn
  function_name           = aws_lambda_function.alerts.arn
  batch_size              = 5
  function_response_types = ["ReportBatchItemFailures"]
  scaling_config {
    maximum_concurrency = 2
  }
  depends_on = [aws_iam_role_policy.lambda, terraform_data.deployment_guard]
}
