output "emr_cluster_id" { value = aws_emr_cluster.congestion.id }
output "emr_cluster_name" { value = aws_emr_cluster.congestion.name }
output "emr_release_label" { value = aws_emr_cluster.congestion.release_label }
output "artifact_key" { value = aws_s3_object.jar.key }
output "results_topic" { value = aws_msk_topic.results.name }
