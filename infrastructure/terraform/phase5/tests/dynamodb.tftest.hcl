mock_provider "aws" {
  mock_resource "aws_dynamodb_table" {
    defaults        = { arn = "arn:aws:dynamodb:ap-south-1:123456789012:table/mock" }
    override_during = plan
  }

  mock_resource "aws_iam_policy" {
    defaults        = { arn = "arn:aws:iam::123456789012:policy/mock" }
    override_during = plan
  }
}

run "deployment_denied_by_default" {
  command         = plan
  expect_failures = [terraform_data.deployment_guard]
}

run "two_owned_on_demand_tables_and_scoped_policies" {
  command = plan

  variables {
    deployment_approved = true # Mock provider only; this does not authorize AWS creation.
    project_name        = "stp5-mock"
  }

  assert {
    condition = (
      aws_dynamodb_table.recommendations.name == "stp5-mock-recommendations" &&
      aws_dynamodb_table.summaries.name == "stp5-mock-summaries" &&
      aws_dynamodb_table.recommendations.billing_mode == "PAY_PER_REQUEST" &&
      aws_dynamodb_table.summaries.billing_mode == "PAY_PER_REQUEST" &&
      aws_dynamodb_table.recommendations.hash_key == "intersection_id" &&
      aws_dynamodb_table.recommendations.range_key == "window_key" &&
      aws_dynamodb_table.summaries.hash_key == "intersection_id" &&
      aws_dynamodb_table.summaries.range_key == "window_key" &&
      aws_dynamodb_table.recommendations.server_side_encryption[0].enabled &&
      aws_dynamodb_table.summaries.server_side_encryption[0].enabled
    )
    error_message = "The managed check needs exactly the approved on-demand, encrypted owned-table keys."
  }

  assert {
    condition = (
      jsondecode(aws_iam_policy.signal_recommendation.policy).Statement[0].Resource == aws_dynamodb_table.recommendations.arn &&
      jsondecode(aws_iam_policy.traffic_analytics.policy).Statement[0].Resource == aws_dynamodb_table.summaries.arn &&
      toset(jsondecode(aws_iam_policy.signal_recommendation.policy).Statement[0].Action) == toset(["dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"]) &&
      toset(jsondecode(aws_iam_policy.traffic_analytics.policy).Statement[0].Action) == toset(["dynamodb:DescribeTable", "dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"])
    )
    error_message = "Each service policy must target only its own table with the repository's required actions."
  }
}
