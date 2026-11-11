variable "deployment_approved" {
  type    = bool
  default = false
}
variable "project_name" { type = string }
module "foundation" {
  source              = "../phase2"
  deployment_approved = var.deployment_approved
  provision_database  = false
  project_name        = "${var.project_name}-net"
}
module "kafka" {
  source                        = "../phase3"
  deployment_approved           = var.deployment_approved
  project_name                  = "${var.project_name}-kafka"
  vpc_id                        = module.foundation.vpc_id
  private_subnet_ids            = module.foundation.private_subnet_ids
  private_route_table_ids       = module.foundation.private_route_table_ids
  application_security_group_id = module.foundation.application_security_group_id
}
module "processing" {
  source                  = "../phase4"
  deployment_approved     = var.deployment_approved
  project_name            = "${var.project_name}-emr"
  vpc_id                  = module.foundation.vpc_id
  private_subnet_ids      = module.foundation.private_subnet_ids
  kafka_cluster_arn       = module.kafka.kafka_cluster_arn
  kafka_security_group_id = module.kafka.kafka_security_group_id
  kafka_bootstrap_servers = module.kafka.kafka_bootstrap_servers
  archive_bucket          = module.kafka.archive_bucket
  s3_prefix_list_id       = module.kafka.s3_prefix_list_id
  jar_path                = "../../../services/congestion-processor/target-emr/congestion-processor-1.0.0.jar"
}
output "emr_cluster_id" { value = module.processing.emr_cluster_id }
output "emr_cluster_name" { value = module.processing.emr_cluster_name }
output "artifact_key" { value = module.processing.artifact_key }
output "kafka_bootstrap_servers" { value = module.kafka.kafka_bootstrap_servers }
output "archive_bucket" { value = module.kafka.archive_bucket }
output "cluster_arn" { value = module.kafka.kafka_cluster_arn }
output "vpc_id" { value = module.foundation.vpc_id }
