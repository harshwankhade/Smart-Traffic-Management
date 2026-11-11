output "database_endpoint" {
  value = var.provision_database ? aws_db_instance.main[0].address : null
}

output "vpc_id" {
  value = aws_vpc.main.id
}

output "application_security_group_id" {
  value = aws_security_group.application.id
}

# Deliberately no credential or secret-value outputs.

output "private_subnet_ids" {
  value = [for subnet in aws_subnet.database : subnet.id]
}

output "private_route_table_ids" {
  value = [aws_route_table.isolated.id]
}
