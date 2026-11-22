mock_provider "aws" {}

run "deployment_denied_by_default" {
  command         = plan
  expect_failures = [terraform_data.deployment_guard]
}
run "retained_artifact_configuration" {
  command = plan
  variables { deployment_approved = true }
  assert {
    condition     = length(aws_ecr_repository.services) == 6 && alltrue([for repo in aws_ecr_repository.services : repo.image_tag_mutability == "IMMUTABLE" && !repo.force_delete])
    error_message = "Keep exactly six immutable repositories with non-forced deletion."
  }
  assert {
    condition     = !aws_s3_bucket.builds.force_destroy && aws_s3_bucket_public_access_block.builds.block_public_acls && aws_s3_bucket_versioning.builds.versioning_configuration[0].status == "Enabled"
    error_message = "Build storage must remain private, versioned and non-forced."
  }
}
