variable "deployment_approved" {
  type    = bool
  default = false
}
variable "project_name" {
  type    = string
  default = "smarttraffic-phase4-emr"
}
variable "vpc_id" { type = string }
variable "private_subnet_ids" {
  type = list(string)
  validation {
    condition     = length(distinct(var.private_subnet_ids)) == 2
    error_message = "Use the two existing isolated Phase 2 subnets."
  }
}
variable "kafka_cluster_arn" { type = string }
variable "kafka_security_group_id" { type = string }
variable "kafka_bootstrap_servers" { type = string }
variable "s3_prefix_list_id" { type = string }
variable "archive_bucket" { type = string }
variable "jar_path" {
  type        = string
  default     = "../../../services/congestion-processor/target-emr/congestion-processor-1.0.0.jar"
  description = "EMR 7.14/Flink 1.20 shaded JAR."
}
variable "emr_instance_type" {
  type        = string
  default     = "m5.xlarge"
  description = "One primary and one core on-demand node for the temporary verification."
}
