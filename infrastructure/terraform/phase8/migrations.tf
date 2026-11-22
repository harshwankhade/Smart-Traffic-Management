# Address-only moves preserve existing archive data when reviewing an upgrade.
# MSK removal and worker replacement still require an explicitly reviewed plan.
moved {
  from = helm_release.argocd_root_application
  to   = helm_release.argocd_root_application[0]
}
moved {
  from = module.streaming.aws_s3_bucket.archive
  to   = aws_s3_bucket.archive
}
moved {
  from = module.streaming.aws_s3_bucket_public_access_block.archive
  to   = aws_s3_bucket_public_access_block.archive
}
moved {
  from = module.streaming.aws_s3_bucket_server_side_encryption_configuration.archive
  to   = aws_s3_bucket_server_side_encryption_configuration.archive
}
moved {
  from = module.streaming.aws_s3_bucket_versioning.archive
  to   = aws_s3_bucket_versioning.archive
}
moved {
  from = module.streaming.aws_s3_bucket_policy.archive
  to   = aws_s3_bucket_policy.archive
}
moved {
  from = module.streaming.aws_vpc_endpoint.s3
  to   = aws_vpc_endpoint.s3
}
moved {
  from = module.streaming.aws_vpc_security_group_egress_rule.application_s3
  to   = aws_vpc_security_group_egress_rule.application_s3
}
moved {
  from = module.streaming.aws_iam_policy.publisher
  to   = aws_iam_policy.publisher_archive
}
