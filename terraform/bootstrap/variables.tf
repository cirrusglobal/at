variable "aws_region" {
  description = "Region for the bootstrap resources."
  type        = string
  default     = "eu-central-1"
}

variable "project" {
  description = "Name prefix for all resources."
  type        = string
  default     = "vpc-api"
}

variable "github_repository" {
  description = "GitHub repository allowed to assume the CI role, as owner/repo."
  type        = string
}

variable "deploy_refs" {
  description = "Git refs permitted to assume the CI role."
  type        = list(string)
  default     = ["refs/heads/main"]
}

variable "deploy_environment" {
  description = <<-EOT
    GitHub environment the deploy job declares. This matters: once a job sets
    `environment:`, GitHub's OIDC subject claim becomes
    repo:<owner>/<repo>:environment:<name> INSTEAD OF the ref form — so a trust
    policy that only allows refs will reject it.
  EOT
  type        = string
  default     = "production"
}

variable "github_oidc_thumbprints" {
  description = <<-EOT
    Certificate thumbprints for GitHub's OIDC issuer. AWS no longer validates
    these for well-known IdPs, but the API still requires the field.
  EOT
  type        = list(string)
  default = [
    "6938fd4d98bab03faadb97b34396831e3780aea1",
    "1c58a3a8518e8759bf075b76b750d4f2df264fcd",
  ]
}
