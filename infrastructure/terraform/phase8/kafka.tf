# The broker is GitOps-owned. Only its trust material and private DNS zone are
# Terraform-owned; no broker endpoint depends on EKS/MSK readiness during apply.
resource "aws_route53_zone" "kafka" {
  name = "smarttraffic.internal"
  vpc { vpc_id = aws_vpc.main.id }
  tags = local.tags
}
resource "tls_private_key" "kafka" {
  algorithm  = "RSA"
  rsa_bits   = 2048
  depends_on = [terraform_data.deployment_guard]
}
resource "tls_self_signed_cert" "kafka" {
  private_key_pem = tls_private_key.kafka.private_key_pem
  subject { common_name = "kafka.smarttraffic.internal" }
  dns_names             = ["kafka.smarttraffic.internal", "kafka", "kafka.smarttraffic.svc.cluster.local", "localhost"]
  validity_period_hours = 2160
  is_ca_certificate     = true
  allowed_uses          = ["key_encipherment", "digital_signature", "server_auth", "cert_signing"]
}
resource "aws_secretsmanager_secret" "kafka_tls" {
  name                    = "${var.project_name}-kafka-tls"
  recovery_window_in_days = 0
  tags                    = local.tags
  depends_on              = [terraform_data.deployment_guard]
}
resource "aws_secretsmanager_secret_version" "kafka_tls" {
  secret_id = aws_secretsmanager_secret.kafka_tls.id
  secret_string = jsonencode({
    "tls.key" = tls_private_key.kafka.private_key_pem_pkcs8
    "tls.crt" = tls_self_signed_cert.kafka.cert_pem
  })
}
resource "aws_s3_object" "kafka_ca" {
  bucket                 = aws_s3_bucket.archive.id
  key                    = "artifacts/kafka-ca.pem"
  content                = tls_self_signed_cert.kafka.cert_pem
  server_side_encryption = "AES256"
}
