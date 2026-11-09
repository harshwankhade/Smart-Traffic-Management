resource "terraform_data" "deployment_guard" {
  lifecycle {
    precondition {
      condition     = var.deployment_approved
      error_message = "Deployment is not approved. Phase 2 permits validate and mocked tests only; preserve the US$5 cap."
    }
  }
}

resource "aws_vpc" "main" {
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
  depends_on           = [terraform_data.deployment_guard]
}

resource "aws_subnet" "database" {
  for_each = {
    "ap-south-1a" = "10.42.10.0/24"
    "ap-south-1b" = "10.42.11.0/24"
  }
  vpc_id                  = aws_vpc.main.id
  availability_zone       = each.key
  cidr_block              = each.value
  map_public_ip_on_launch = false
}

# No Internet gateway, NAT gateway or default Internet route is defined.
resource "aws_route_table" "isolated" {
  vpc_id = aws_vpc.main.id
  route  = []
}

resource "aws_route_table_association" "database" {
  for_each       = aws_subnet.database
  subnet_id      = each.value.id
  route_table_id = aws_route_table.isolated.id
}

# A later authorized deployment attaches this group to actual application workloads.
resource "aws_security_group" "application" {
  name_prefix = "${var.project_name}-app-"
  description = "Application identity; database-only egress in this foundation"
  vpc_id      = aws_vpc.main.id
}

resource "aws_security_group" "database" {
  name_prefix = "${var.project_name}-db-"
  description = "Private PostgreSQL, restricted to application security group"
  vpc_id      = aws_vpc.main.id
}

resource "aws_vpc_security_group_ingress_rule" "postgres" {
  security_group_id            = aws_security_group.database.id
  referenced_security_group_id = aws_security_group.application.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_vpc_security_group_egress_rule" "application_database" {
  security_group_id            = aws_security_group.application.id
  referenced_security_group_id = aws_security_group.database.id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
}

resource "aws_db_subnet_group" "main" {
  name       = var.project_name
  subnet_ids = [for subnet in aws_subnet.database : subnet.id]
}

resource "aws_db_parameter_group" "main" {
  name_prefix = "${var.project_name}-"
  family      = "postgres17"
  parameter {
    name  = "rds.force_ssl"
    value = "1"
  }
}

resource "aws_db_instance" "main" {
  identifier                          = var.project_name
  engine                              = "postgres"
  engine_version                      = "17"
  instance_class                      = "db.t4g.micro"
  allocated_storage                   = 20
  storage_type                        = "gp3"
  storage_encrypted                   = true
  db_name                             = "smarttraffic"
  username                            = "traffic_admin"
  manage_master_user_password         = true
  iam_database_authentication_enabled = true
  db_subnet_group_name                = aws_db_subnet_group.main.name
  parameter_group_name                = aws_db_parameter_group.main.name
  vpc_security_group_ids              = [aws_security_group.database.id]
  publicly_accessible                 = false
  multi_az                            = false
  port                                = 5432
  backup_retention_period             = 1
  deletion_protection                 = true
  skip_final_snapshot                 = false
  final_snapshot_identifier           = "${var.project_name}-final"
  auto_minor_version_upgrade          = true
}
