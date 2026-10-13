data "aws_iam_policy_document" "ec2_assume" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

data "aws_iam_policy_document" "ecr_read" {
  statement {
    sid       = "EcrAuth"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"]
  }

  statement {
    sid = "EcrPullServiceB"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = [aws_ecr_repository.service_b.arn]
  }
}

data "aws_iam_policy_document" "telemetry" {
  count = var.create_instance ? 1 : 0

  statement {
    sid = "CloudWatchLogGroup"
    actions = [
      "logs:CreateLogGroup",
      "logs:DescribeLogStreams",
    ]
    resources = [aws_cloudwatch_log_group.telemetry[0].arn]
  }

  statement {
    sid = "CloudWatchLogStream"
    actions = [
      "logs:CreateLogStream",
      "logs:PutLogEvents",
    ]
    resources = ["${aws_cloudwatch_log_group.telemetry[0].arn}:*"]
  }

  statement {
    sid       = "CloudWatchDescribeLogGroups"
    actions   = ["logs:DescribeLogGroups"]
    resources = ["*"]
  }

  statement {
    sid = "XRayWrite"
    actions = [
      "xray:GetSamplingRules",
      "xray:GetSamplingStatisticSummaries",
      "xray:GetSamplingTargets",
      "xray:PutTelemetryRecords",
      "xray:PutTraceSegments",
    ]
    resources = ["*"]
  }
}

resource "aws_iam_role" "ec2" {
  count              = var.create_instance ? 1 : 0
  name               = "${local.name}-ec2"
  assume_role_policy = data.aws_iam_policy_document.ec2_assume.json

  tags = merge(local.common_tags, {
    Name = "${local.name}-ec2"
  })
}

resource "aws_iam_role_policy_attachment" "ssm" {
  count      = var.create_instance ? 1 : 0
  role       = aws_iam_role.ec2[0].name
  policy_arn = "arn:aws:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_role_policy" "ecr_read" {
  count  = var.create_instance ? 1 : 0
  name   = "${local.name}-ecr-read"
  role   = aws_iam_role.ec2[0].id
  policy = data.aws_iam_policy_document.ecr_read.json
}

resource "aws_iam_role_policy" "telemetry" {
  count  = var.create_instance ? 1 : 0
  name   = "${local.name}-telemetry"
  role   = aws_iam_role.ec2[0].id
  policy = data.aws_iam_policy_document.telemetry[0].json
}

resource "aws_iam_instance_profile" "ec2" {
  count = var.create_instance ? 1 : 0
  name  = "${local.name}-ec2"
  role  = aws_iam_role.ec2[0].name

  tags = merge(local.common_tags, {
    Name = "${local.name}-ec2"
  })
}
