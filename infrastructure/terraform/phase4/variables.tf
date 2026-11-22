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
variable "kafka_auth_mode" {
  type    = string
  default = "iam"
  validation {
    condition     = contains(["iam", "tls"], var.kafka_auth_mode)
    error_message = "Use iam for MSK or tls for the private EKS broker."
  }
}
variable "kafka_port" {
  type    = number
  default = 9098
}
variable "kafka_cidr" {
  type        = string
  default     = null
  description = "Private VPC CIDR for the internal NLB; required in tls mode."
}
variable "s3_prefix_list_id" { type = string }
variable "bootstrap_dependency_ids" {
  type        = list(string)
  default     = []
  description = "Prerequisite NAT/routes/Logs endpoint IDs; only cluster creation waits for these."
}
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
variable "emr_single_node" {
  type        = bool
  default     = false
  description = "Run only the primary node when the account vCPU quota requires a single-node EMR cluster."
}
