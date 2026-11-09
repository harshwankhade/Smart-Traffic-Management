# All runs use an AWS mock. No real AWS API calls or applies.
mock_provider "aws" {}

run "deployment_denied_by_default" {
  command         = plan
  expect_failures = [terraform_data.deployment_guard]
}

run "private_database_foundation" {
  command = plan
  variables {
    deployment_approved = true # Only for the mock provider, not deployment approval.
  }

  assert {
    condition = (
      aws_db_instance.main.engine == "postgres" &&
      aws_db_instance.main.engine_version == "17" &&
      aws_db_instance.main.instance_class == "db.t4g.micro" &&
      aws_db_instance.main.allocated_storage == 20 &&
      aws_db_instance.main.storage_type == "gp3"
    )
    error_message = "Database must match the approved Phase 2 size and engine."
  }

  assert {
    condition = (
      aws_db_instance.main.storage_encrypted &&
      !aws_db_instance.main.publicly_accessible &&
      !aws_db_instance.main.multi_az &&
      aws_db_instance.main.manage_master_user_password &&
      aws_db_instance.main.iam_database_authentication_enabled &&
      aws_db_instance.main.deletion_protection &&
      aws_db_instance.main.password == null
    )
    error_message = "Database privacy, encryption and secret management must be preserved."
  }

  assert {
    condition     = anytrue([for parameter in aws_db_parameter_group.main.parameter : parameter.name == "rds.force_ssl" && parameter.value == "1"])
    error_message = "PostgreSQL must require encrypted connections."
  }

  assert {
    condition = (
      length(aws_subnet.database) == 2 &&
      alltrue([for subnet in aws_subnet.database : !subnet.map_public_ip_on_launch]) &&
      length(aws_route_table_association.database) == 2 &&
      length(aws_route_table.isolated.route) == 0
    )
    error_message = "Database subnets must be isolated across two AZs with no Internet routes."
  }

  assert {
    condition = (
      aws_vpc_security_group_ingress_rule.postgres.from_port == 5432 &&
      aws_vpc_security_group_ingress_rule.postgres.to_port == 5432 &&
      aws_vpc_security_group_ingress_rule.postgres.ip_protocol == "tcp" &&
      aws_vpc_security_group_ingress_rule.postgres.cidr_ipv4 == null &&
      aws_vpc_security_group_ingress_rule.postgres.cidr_ipv6 == null
    )
    error_message = "Database ingress must use a security group, not a public CIDR."
  }
}
