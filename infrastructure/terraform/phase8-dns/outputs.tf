output "hosted_zone_id" {
  value = local.hosted_zone_id
}

output "route53_nameservers" {
  value = local.hosted_zone_nameservers
}

output "public_api_hostname" {
  value = var.public_api_hostname
}

output "public_api_certificate_arn" {
  value = try(aws_acm_certificate_validation.public_api[0].certificate_arn, null)
}
