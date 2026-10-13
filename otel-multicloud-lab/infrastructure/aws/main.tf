locals {
  name = "otel-multicloud-lab"

  common_tags = {
    Project     = "otel-multicloud-lab"
    Environment = "university-lab"
  }

  log_group_name = "/otel-multicloud-lab/university-lab"

  postgres_image = "postgres:16-alpine"
  adot_image     = "public.ecr.aws/aws-observability/aws-otel-collector:v0.50.0"

  ami_id          = try(trimspace(data.aws_ssm_parameter.amazon_linux_2023[0].value), null)
  subnet_id       = var.subnet_id != null ? var.subnet_id : try(sort(data.aws_subnets.default_public[0].ids)[0], null)
  ecr_registry    = split("/", aws_ecr_repository.service_b.repository_url)[0]
  service_b_image = "${aws_ecr_repository.service_b.repository_url}:${var.service_b_image_tag}"
}

data "aws_ssm_parameter" "amazon_linux_2023" {
  count = var.create_instance ? 1 : 0
  name  = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-x86_64"
}

resource "random_password" "postgres" {
  count       = var.create_instance ? 1 : 0
  length      = 32
  special     = false
  min_lower   = 1
  min_upper   = 1
  min_numeric = 1
}

resource "aws_cloudwatch_log_group" "telemetry" {
  count             = var.create_instance ? 1 : 0
  name              = local.log_group_name
  retention_in_days = 1

  tags = merge(local.common_tags, {
    Name = local.log_group_name
  })
}
