output "emr_cluster_id" { value = aws_cloudformation_stack.congestion.outputs["ClusterId"] }
output "emr_cluster_name" { value = aws_cloudformation_stack.congestion.outputs["ClusterName"] }
output "emr_release_label" { value = "emr-7.14.0" }
output "artifact_key" { value = aws_s3_object.jar.key }
output "results_topic" { value = aws_msk_topic.results.name }
output "cloudwatch_logs_endpoint_security_group_id" { value = aws_security_group.cloudwatch_logs_endpoint.id }
