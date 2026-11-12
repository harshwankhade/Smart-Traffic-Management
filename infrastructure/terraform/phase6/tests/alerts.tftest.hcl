mock_provider "aws" {
  mock_resource "aws_sqs_queue" {
    defaults = {
      arn = "arn:aws:sqs:ap-south-1:123456789012:mock"
      url = "https://sqs.ap-south-1.amazonaws.com/123456789012/mock"
    }
    override_during = plan
  }
  mock_resource "aws_dynamodb_table" {
    defaults        = { arn = "arn:aws:dynamodb:ap-south-1:123456789012:table/mock" }
    override_during = plan
  }
  mock_resource "aws_cloudwatch_log_group" {
    defaults        = { arn = "arn:aws:logs:ap-south-1:123456789012:log-group:mock" }
    override_during = plan
  }
  mock_resource "aws_iam_role" {
    defaults        = { arn = "arn:aws:iam::123456789012:role/mock" }
    override_during = plan
  }
  mock_resource "aws_iam_policy" {
    defaults        = { arn = "arn:aws:iam::123456789012:policy/mock" }
    override_during = plan
  }
  mock_resource "aws_lambda_function" {
    defaults        = { arn = "arn:aws:lambda:ap-south-1:123456789012:function:mock" }
    override_during = plan
  }
}

run "deployment_denied_by_default" {
  command         = plan
  expect_failures = [terraform_data.deployment_guard]
}

run "queue_function_table_and_scoped_permissions" {
  command = plan

  variables {
    deployment_approved = true # Mock provider only; does not authorize AWS creation.
    project_name        = "stp6-mock"
  }

  assert {
    condition = (
      aws_sqs_queue.alerts.visibility_timeout_seconds == 60 &&
      aws_sqs_queue.alerts.sqs_managed_sse_enabled &&
      aws_sqs_queue.dlq.sqs_managed_sse_enabled &&
      jsondecode(aws_sqs_queue.alerts.redrive_policy).maxReceiveCount == 5 &&
      jsondecode(aws_sqs_queue.alerts.redrive_policy).deadLetterTargetArn == aws_sqs_queue.dlq.arn &&
      aws_dynamodb_table.alerts.billing_mode == "PAY_PER_REQUEST" &&
      aws_dynamodb_table.alerts.hash_key == "alert_id" &&
      aws_dynamodb_table.alerts.server_side_encryption[0].enabled
    )
    error_message = "Queue/DLQ and owned DynamoDB settings changed."
  }

  assert {
    condition = (
      aws_lambda_function.alerts.runtime == "python3.14" &&
      aws_lambda_function.alerts.handler == "handler.handler" &&
      aws_lambda_function.alerts.timeout == 10 &&
      aws_lambda_function.alerts.memory_size == 128 &&
      aws_lambda_event_source_mapping.alerts.batch_size == 5 &&
      toset(aws_lambda_event_source_mapping.alerts.function_response_types) == toset(["ReportBatchItemFailures"]) &&
      aws_lambda_event_source_mapping.alerts.scaling_config[0].maximum_concurrency == 2 &&
      aws_cloudwatch_log_group.alerts.retention_in_days == 7
    )
    error_message = "Lambda runtime, trigger or logging settings changed."
  }

  assert {
    condition = (
      toset(jsondecode(aws_iam_role_policy.lambda.policy).Statement[0].Action) == toset(["sqs:ReceiveMessage", "sqs:DeleteMessage", "sqs:GetQueueAttributes"]) &&
      jsondecode(aws_iam_role_policy.lambda.policy).Statement[0].Resource == aws_sqs_queue.alerts.arn &&
      toset(jsondecode(aws_iam_role_policy.lambda.policy).Statement[1].Action) == toset(["dynamodb:PutItem", "dynamodb:GetItem"]) &&
      jsondecode(aws_iam_role_policy.lambda.policy).Statement[1].Resource == aws_dynamodb_table.alerts.arn &&
      jsondecode(aws_iam_policy.signal_recommendation_send.policy).Statement[0].Action == ["sqs:SendMessage"] &&
      jsondecode(aws_iam_policy.signal_recommendation_send.policy).Statement[0].Resource == aws_sqs_queue.alerts.arn &&
      jsondecode(aws_iam_policy.incident_manager_send.policy).Statement[0].Action == ["sqs:SendMessage"] &&
      jsondecode(aws_iam_policy.incident_manager_send.policy).Statement[0].Resource == aws_sqs_queue.alerts.arn
    )
    error_message = "Runtime or producer policies are broader than the required resources/actions."
  }
}
