data "aws_vpc" "integrator" {
  count   = var.create_integrator_data ? 1 : 0
  default = true
}

data "aws_subnets" "integrator" {
  count = var.create_integrator_data ? 1 : 0

  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.integrator[0].id]
  }

  filter {
    name   = "default-for-az"
    values = ["true"]
  }
}

resource "aws_security_group" "rds" {
  count       = var.create_integrator_data ? 1 : 0
  name        = "otel-multicloud-lab-data"
  description = "PostgreSQL solo desde la IP estatica de Cloud NAT"
  vpc_id      = data.aws_vpc.integrator[0].id

  tags = merge(local.common_tags, {
    Name      = "otel-multicloud-lab-data"
    Component = "integrator-data"
  })
}

resource "aws_vpc_security_group_ingress_rule" "rds_from_cloud_nat" {
  count             = var.create_integrator_data ? 1 : 0
  security_group_id = aws_security_group.rds[0].id
  description       = "PostgreSQL desde Cloud NAT de GCP"
  ip_protocol       = "tcp"
  from_port         = 5432
  to_port           = 5432
  cidr_ipv4         = var.gcp_egress_cidr

  tags = merge(local.common_tags, {
    Name      = "otel-multicloud-lab-data-postgres"
    Component = "integrator-data"
  })
}

resource "aws_db_subnet_group" "integrator" {
  count      = var.create_integrator_data ? 1 : 0
  name       = "otel-multicloud-lab-data"
  subnet_ids = data.aws_subnets.integrator[0].ids

  tags = merge(local.common_tags, {
    Name      = "otel-multicloud-lab-data"
    Component = "integrator-data"
  })

  lifecycle {
    precondition {
      condition     = length(data.aws_subnets.integrator[0].ids) >= 2
      error_message = "RDS necesita al menos dos zonas en la VPC predeterminada. No se crea una NAT Gateway."
    }
  }
}

resource "aws_db_parameter_group" "integrator" {
  count = var.create_integrator_data ? 1 : 0

  name   = "otel-multicloud-lab-data"
  family = "postgres16"

  parameter {
    name         = "rds.force_ssl"
    value        = "1"
    apply_method = "immediate"
  }

  tags = merge(local.common_tags, {
    Name      = "otel-multicloud-lab-data"
    Component = "integrator-data"
  })
}

resource "aws_db_instance" "integrator" {
  count = var.create_integrator_data ? 1 : 0

  identifier        = "otel-multicloud-lab-data"
  engine            = "postgres"
  engine_version    = "16"
  instance_class    = "db.t4g.micro"
  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true

  db_name                     = "otel_integrator"
  username                    = "data_service"
  manage_master_user_password = true
  port                        = 5432

  publicly_accessible    = true
  multi_az               = false
  db_subnet_group_name   = aws_db_subnet_group.integrator[0].name
  vpc_security_group_ids = [aws_security_group.rds[0].id]
  parameter_group_name   = aws_db_parameter_group.integrator[0].name

  backup_retention_period    = 0
  deletion_protection        = false
  skip_final_snapshot        = true
  apply_immediately          = true
  auto_minor_version_upgrade = true

  performance_insights_enabled = false
  monitoring_interval          = 0

  tags = merge(local.common_tags, {
    Name      = "otel-multicloud-lab-data"
    Component = "integrator-data"
  })
}
