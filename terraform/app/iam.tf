data "aws_iam_policy_document" "lambda_assume_role" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "lambda" {
  name               = "${var.project}-lambda"
  assume_role_policy = data.aws_iam_policy_document.lambda_assume_role.json
}

data "aws_iam_policy_document" "lambda" {
  # Exactly the EC2 calls app/services/vpc.py makes, and nothing else.
  # CreateTags is required for the TagSpecifications passed at creation time.
  statement {
    sid    = "NetworkProvisioning"
    effect = "Allow"
    actions = [
      "ec2:CreateVpc",
      "ec2:DeleteVpc",
      "ec2:DescribeVpcs",
      "ec2:ModifyVpcAttribute",
      "ec2:CreateSubnet",
      "ec2:DeleteSubnet",
      "ec2:ModifySubnetAttribute",
      "ec2:CreateInternetGateway",
      "ec2:AttachInternetGateway",
      "ec2:DetachInternetGateway",
      "ec2:DeleteInternetGateway",
      "ec2:CreateRouteTable",
      "ec2:DeleteRouteTable",
      "ec2:DescribeRouteTables",
      "ec2:CreateRoute",
      "ec2:AssociateRouteTable",
      "ec2:DisassociateRouteTable",
      "ec2:CreateTags",
    ]

    # Most EC2 Create* actions cannot be restricted by resource, because the
    # resource does not exist when the call is authorised.
    resources = ["*"]
  }

  # Confines destructive calls to resources this service actually created.
  # Create* actions are covered by the RequestTag condition below.
  statement {
    sid    = "OnlyTouchOwnResources"
    effect = "Deny"
    actions = [
      "ec2:DeleteVpc",
      "ec2:DeleteSubnet",
      "ec2:DeleteInternetGateway",
      "ec2:DeleteRouteTable",
      "ec2:DetachInternetGateway",
    ]
    resources = ["*"]

    condition {
      test     = "StringNotEquals"
      variable = "ec2:ResourceTag/ManagedBy"
      values   = [var.project]
    }
  }

  # No ListTables or CreateTable: the table is managed by Terraform, and the
  # application runs with AUTO_CREATE_TABLE=false.
  statement {
    sid    = "NetworkRecords"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:PutItem",
      "dynamodb:DeleteItem",
      "dynamodb:Query",
    ]
    resources = [
      aws_dynamodb_table.networks.arn,
      "${aws_dynamodb_table.networks.arn}/index/*",
    ]
  }

  statement {
    sid    = "Logging"
    effect = "Allow"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.api.arn}:*"]
  }
}

resource "aws_iam_role_policy" "lambda" {
  name   = "${var.project}-lambda"
  role   = aws_iam_role.lambda.id
  policy = data.aws_iam_policy_document.lambda.json
}
