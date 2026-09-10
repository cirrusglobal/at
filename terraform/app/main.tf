data "aws_caller_identity" "current" {}

# Created by the bootstrap stack; referenced, not managed, here.
data "aws_ecr_repository" "app" {
  name = var.project
}

# ------------------------------------------------------------------ storage

# Key schema mirrors app/services/repository.py. The GSI is what lets listing
# use a Query with a constant partition key instead of a full table Scan.
resource "aws_dynamodb_table" "networks" {
  name         = "${var.project}-networks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "network_id"

  attribute {
    name = "network_id"
    type = "S"
  }

  attribute {
    name = "entity_type"
    type = "S"
  }

  attribute {
    name = "created_at"
    type = "S"
  }

  global_secondary_index {
    name            = "by_created_at"
    hash_key        = "entity_type"
    range_key       = "created_at"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = true
  }
}

# ------------------------------------------------------------------ secrets

# Generated rather than configured, so no credential is ever committed or
# typed. Both are exposed as sensitive outputs for the operator to read once.
resource "random_password" "jwt_secret" {
  length  = 48
  special = false
}

resource "random_password" "demo_password" {
  length  = 24
  special = false
}

# ------------------------------------------------------------------ logging

# Declared explicitly so retention is bounded. Lambda auto-creates this group
# on first invocation with retention set to "never expire".
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${var.project}-api"
  retention_in_days = var.log_retention_days
}
