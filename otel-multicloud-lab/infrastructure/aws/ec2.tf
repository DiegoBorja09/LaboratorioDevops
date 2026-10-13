resource "aws_instance" "lab" {
  count                       = var.create_instance ? 1 : 0
  ami                         = local.ami_id
  instance_type               = var.instance_type
  subnet_id                   = local.subnet_id
  vpc_security_group_ids      = [aws_security_group.lab[0].id]
  iam_instance_profile        = aws_iam_instance_profile.ec2[0].name
  associate_public_ip_address = true
  user_data = templatefile("${path.module}/user-data.sh.tftpl", {
    aws_region            = var.aws_region
    postgres_user         = var.postgres_user
    postgres_password     = random_password.postgres[0].result
    postgres_db           = var.postgres_db
    postgres_image        = local.postgres_image
    adot_image            = local.adot_image
    service_b_image       = local.service_b_image
    ecr_registry          = local.ecr_registry
    service_b_port        = var.service_b_port
    log_group_name        = local.log_group_name
    grafana_otlp_endpoint = var.grafana_otlp_endpoint
    grafana_otlp_auth     = var.grafana_otlp_auth
  })
  user_data_replace_on_change = true

  metadata_options {
    http_endpoint               = "enabled"
    http_tokens                 = "required"
    http_put_response_hop_limit = 2
  }

  root_block_device {
    volume_type           = "gp3"
    volume_size           = 8
    encrypted             = true
    delete_on_termination = true
  }

  tags = merge(local.common_tags, {
    Name = local.name
  })

  depends_on = [
    aws_cloudwatch_log_group.telemetry,
    aws_iam_role_policy.telemetry,
    aws_iam_role_policy.ecr_read,
    aws_iam_role_policy_attachment.ssm,
  ]
}
