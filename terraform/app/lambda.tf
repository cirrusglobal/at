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

# An HTTP API rather than a Lambda Function URL.
#
# A Function URL would be one fewer service and allow a 15-minute timeout, but
# in this account public Function URLs return 403 regardless of the function's
# resource policy — verified with a correct policy, no SCPs, and a freshly
# recreated URL, while `lambda invoke` on the same function returned 200. An
# HTTP API is unaffected, and is in any case the more conventional front door.
#
# The 29s integration cap that comes with it is not a constraint here:
# provisioning a VPC with subnets completes in well under 10s.
resource "aws_apigatewayv2_api" "api" {
  name          = "${var.project}-api"
  protocol_type = "HTTP"
}

resource "aws_apigatewayv2_integration" "api" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0" # the event shape Mangum expects
}

# $default catches every method and path, leaving routing to FastAPI rather
# than duplicating it in the gateway.
resource "aws_apigatewayv2_route" "default" {
  api_id    = aws_apigatewayv2_api.api.id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.api.id}"
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true

  default_route_settings {
    # Cheap insurance on a public endpoint that provisions billable resources.
    throttling_burst_limit = 20
    throttling_rate_limit  = 10
  }
}

resource "aws_lambda_permission" "api_gateway" {
  statement_id  = "AllowInvokeFromApiGateway"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}
