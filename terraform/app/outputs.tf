output "api_url" {
  description = "Public HTTPS endpoint for the API."
  value       = aws_lambda_function_url.api.function_url
}

output "docs_url" {
  description = "Interactive OpenAPI documentation."
  value       = "${aws_lambda_function_url.api.function_url}docs"
}

output "dynamodb_table" {
  description = "Table holding the provisioned network records."
  value       = aws_dynamodb_table.networks.name
}

output "demo_username" {
  value = var.demo_username
}

output "demo_password" {
  description = "Read once with: terraform output -raw demo_password"
  value       = random_password.demo_password.result
  sensitive   = true
}
