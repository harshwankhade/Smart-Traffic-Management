locals {
  tags = {
    Project   = "SmartTraffic"
    Phase     = "8"
    Component = "dns-certificate"
    ManagedBy = "Terraform"
  }
}

# This state owns the domain delegation and its ALB certificate independently
# from the later EKS/MSK/EMR state.
data "aws_route53_zone" "existing" {
  count   = var.existing_hosted_zone_id == null ? 0 : 1
  zone_id = var.existing_hosted_zone_id
}

resource "aws_route53_zone" "public" {
  count = var.existing_hosted_zone_id == null ? 1 : 0
  name  = var.domain_name
  tags  = local.tags
}

locals {
  hosted_zone_id          = var.existing_hosted_zone_id == null ? aws_route53_zone.public[0].zone_id : data.aws_route53_zone.existing[0].zone_id
  hosted_zone_nameservers = var.existing_hosted_zone_id == null ? aws_route53_zone.public[0].name_servers : data.aws_route53_zone.existing[0].name_servers
}

resource "aws_acm_certificate" "public_api" {
  count             = var.certificate_enabled ? 1 : 0
  domain_name       = var.public_api_hostname
  validation_method = "DNS"
  tags              = local.tags

  lifecycle {
    precondition {
      condition     = endswith(var.public_api_hostname, ".${var.domain_name}")
      error_message = "public_api_hostname must be inside domain_name."
    }
  }
}

resource "aws_route53_record" "public_api_validation" {
  for_each = var.certificate_enabled ? {
    for option in aws_acm_certificate.public_api[0].domain_validation_options : option.domain_name => option
  } : {}

  zone_id         = local.hosted_zone_id
  name            = each.value.resource_record_name
  type            = each.value.resource_record_type
  ttl             = 60
  records         = [each.value.resource_record_value]
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "public_api" {
  count                   = var.certificate_enabled ? 1 : 0
  certificate_arn         = aws_acm_certificate.public_api[0].arn
  validation_record_fqdns = [for record in aws_route53_record.public_api_validation : record.fqdn]
}
