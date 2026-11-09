output "database_endpoint" {
  value = aws_db_instance.main.address
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "application_security_group_id" {
  value = aws_security_group.application.id
}

# Deliberately no credential or secret-value outputs.
