output "alert_queue_url" {
  value = aws_sqs_queue.alerts.url
}

output "alert_queue_arn" {
  value = aws_sqs_queue.alerts.arn
}

output "dlq_url" {
  value = aws_sqs_queue.dlq.url
}

output "alert_table_name" {
  value = aws_dynamodb_table.alerts.name
}

output "lambda_function_name" {
  value = aws_lambda_function.alerts.function_name
}

output "event_source_mapping_uuid" {
  value = aws_lambda_event_source_mapping.alerts.uuid
}

output "signal_recommendation_send_policy_arn" {
  value = aws_iam_policy.signal_recommendation_send.arn
}

output "incident_manager_send_policy_arn" {
  value = aws_iam_policy.incident_manager_send.arn
}
