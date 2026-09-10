output "state_bucket" {
  description = "Pass to the app stack as -backend-config=\"bucket=...\"."
  value       = aws_s3_bucket.state.id
}

output "ci_role_arn" {
  description = "Set as the AWS_ROLE_ARN repository variable in GitHub."
  value       = aws_iam_role.ci.arn
}

output "ecr_repository_url" {
  description = "Image repository CI pushes to."
  value       = aws_ecr_repository.app.repository_url
}
