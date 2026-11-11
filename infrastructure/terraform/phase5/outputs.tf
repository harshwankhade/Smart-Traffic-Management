output "recommendations_table" {
  value = aws_dynamodb_table.recommendations.name
}

output "summaries_table" {
  value = aws_dynamodb_table.summaries.name
}

output "signal_recommendation_policy_arn" {
  value = aws_iam_policy.signal_recommendation.arn
}

output "traffic_analytics_policy_arn" {
  value = aws_iam_policy.traffic_analytics.arn
}
