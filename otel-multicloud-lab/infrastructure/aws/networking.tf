data "aws_vpc" "default" {
  count   = var.create_instance ? 1 : 0
  default = true
}

data "aws_subnets" "default_public" {
  count = var.create_instance ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.default[0].id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }

  filter {
    name   = "map-public-ip-on-launch"
    values = ["true"]
  }
}

resource "aws_security_group" "lab" {
  count       = var.create_instance ? 1 : 0
  name        = local.name
  description = "Demostracion universitaria: solo TCP 8082 desde Internet"
  vpc_id      = data.aws_vpc.default[0].id

  tags = merge(local.common_tags, {
    Name = local.name
  })
}

resource "aws_vpc_security_group_ingress_rule" "service_b" {
  count             = var.create_instance ? 1 : 0
  security_group_id = aws_security_group.lab[0].id
  description       = "HTTP de service-b para la demostracion"
  ip_protocol       = "tcp"
  from_port         = var.service_b_port
  to_port           = var.service_b_port
  cidr_ipv4         = "0.0.0.0/0"

  tags = merge(local.common_tags, {
    Name = "${local.name}-service-b"
  })
}

resource "aws_vpc_security_group_egress_rule" "aws_and_images" {
  count             = var.create_instance ? 1 : 0
  security_group_id = aws_security_group.lab[0].id
  description       = "Salida para SSM, ECR, imagenes publicas y telemetria"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"

  tags = merge(local.common_tags, {
    Name = "${local.name}-egress"
  })
}
