variable "aws_region" {
  description = "Region to deploy into."
  type        = string
  default     = "eu-central-1"
}

variable "project" {
  description = "Name prefix for all resources. Must match the bootstrap stack."
  type        = string
  default     = "vpc-api"
}

variable "image_tag" {
  description = "ECR image tag to deploy. CI passes the commit SHA."
  type        = string
}

variable "lambda_memory_mb" {
  description = "Lambda memory. CPU scales with this."
  type        = number
  default     = 512
}

variable "lambda_timeout_seconds" {
  description = <<-EOT
    Provisioning a VPC with subnets takes well under 10s. Function URLs allow
    up to 15 minutes, so there is generous headroom — unlike API Gateway, which
    caps integrations at 29s.
  EOT
  type        = number
  default     = 60
}

variable "log_retention_days" {
  description = "CloudWatch log retention. Lambda would otherwise keep logs forever."
  type        = number
  default     = 14
}

variable "demo_username" {
  description = "Seeded API user. The password is generated, not configured."
  type        = string
  default     = "demo"
}
