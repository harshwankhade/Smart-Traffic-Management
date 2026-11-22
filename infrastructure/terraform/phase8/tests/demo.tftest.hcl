mock_provider "aws" {
  mock_resource "aws_db_instance" {
    defaults = {
      master_user_secret = [{ secret_arn = "arn:aws:secretsmanager:ap-south-1:123456789012:secret:mock", secret_status = "active", kms_key_id = "mock" }]
    }
    override_during = plan
  }
}
mock_provider "helm" {}
mock_provider "tls" {}

# Legacy phase modules configure their own AWS provider. Stub their outputs in
# this composition test; exercise their real resources in their own mock tests.
override_module {
  target = module.processing
  outputs = {
    emr_cluster_id                             = "j-MOCK"
    artifact_key                               = "artifacts/processor.jar"
    cloudwatch_logs_endpoint_security_group_id = "sg-mock"
  }
}
override_module {
  target = module.derived
  outputs = {
    recommendations_table            = "mock-recommendations"
    summaries_table                  = "mock-summaries"
    signal_recommendation_policy_arn = "arn:aws:iam::123456789012:policy/recommendations"
    traffic_analytics_policy_arn     = "arn:aws:iam::123456789012:policy/summaries"
  }
}
override_module {
  target = module.alerts
  outputs = {
    alert_queue_url                       = "https://sqs.ap-south-1.amazonaws.com/123456789012/mock"
    incident_manager_send_policy_arn      = "arn:aws:iam::123456789012:policy/incident"
    signal_recommendation_send_policy_arn = "arn:aws:iam::123456789012:policy/congestion"
  }
}

variables {
  admin_cidrs            = ["192.0.2.1/32"]
  public_dns_name        = "api.example.com"
  route53_zone_id        = "ZMOCK"
  public_certificate_arn = "arn:aws:acm:ap-south-1:123456789012:certificate/mock"
}

run "demo_shape_and_artifact_ownership" {
  command = plan
  variables { deployment_approved = true }
  assert {
    condition     = contains(aws_eks_node_group.main.instance_types, "t3.large") && length(aws_eks_node_group.main.instance_types) == 1 && aws_eks_node_group.main.scaling_config[0].desired_size == 2
    error_message = "The light demo must default to two t3.large workers."
  }
  assert {
    condition     = length(data.aws_ecr_repository.services) == 6 && output.kafka_bootstrap_servers == "kafka.smarttraffic.internal:9093"
    error_message = "Read retained images and advertise only the private TLS Kafka endpoint."
  }
}

run "hpa_validation_keeps_worker_headroom" {
  command = plan
  variables {
    deployment_approved = true
    eks_worker_count    = 4
  }
  assert {
    condition = (
      aws_eks_node_group.main.scaling_config[0].desired_size == 4 &&
      aws_eks_node_group.main.scaling_config[0].min_size == 4 &&
      aws_eks_node_group.main.scaling_config[0].max_size == 4
    )
    error_message = "HPA validation requires its explicitly selected four-worker capacity."
  }
}

run "infrastructure_can_start_before_gitops_publication" {
  command = plan
  variables {
    deployment_approved      = true
    gitops_bootstrap_enabled = false
  }
  assert {
    condition     = length(helm_release.argocd_root_application) == 0
    error_message = "Initial provisioning must not deploy the previous Git revision."
  }
}

run "runtime_creation_stays_guarded" {
  command = plan
  variables { deployment_approved = false }
  expect_failures = [terraform_data.deployment_guard]
}
