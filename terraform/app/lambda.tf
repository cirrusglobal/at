resource "aws_lambda_function" "api" {
  function_name = "${var.project}-api"
  role          = aws_iam_role.lambda.arn

  package_type = "Image"
  image_uri    = "${data.aws_ecr_repository.app.repository_url}:${var.image_tag}"

  timeout     = var.lambda_timeout_seconds
  memory_size = var.lambda_memory_mb

  environment {
    variables = {
      # AWS_REGION is deliberately absent: Lambda reserves that name and
      # rejects any attempt to set it, while also populating it in the runtime
      # environment — which is exactly where pydantic-settings reads it from.
      DYNAMODB_TABLE_NAME = aws_dynamodb_table.networks.name
      AUTO_CREATE_TABLE   = "false"
      MANAGED_BY_TAG      = var.project
      JWT_SECRET          = random_password.jwt_secret.result
      DEMO_USERNAME       = var.demo_username
      DEMO_PASSWORD       = random_password.demo_password.result
    }
  }

  # Without this the function would create the log group itself, unbounded.
  depends_on = [
    aws_cloudwatch_log_group.api,
    aws_iam_role_policy.lambda,
  ]
}

# A Function URL rather than API Gateway: one fewer service, a 15-minute
# ceiling instead of 29 seconds, and no per-request API Gateway charge.
resource "aws_lambda_function_url" "api" {
  function_name = aws_lambda_function.api.function_name

  # NONE means unsigned requests reach the function — the application's bearer
  # token layer is the auth boundary. AWS_IAM here would require every caller
  # to SigV4-sign requests, which is incompatible with the OAuth2 flow the
  # brief asks for.
  authorization_type = "NONE"
}
