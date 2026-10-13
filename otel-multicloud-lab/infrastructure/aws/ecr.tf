resource "aws_ecr_repository" "service_b" {
  name                 = "${local.name}-service-b"
  image_tag_mutability = "MUTABLE"
  force_delete         = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  tags = merge(local.common_tags, {
    Name = "${local.name}-service-b"
  })
}

resource "aws_ecr_lifecycle_policy" "service_b" {
  repository = aws_ecr_repository.service_b.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Conservar como maximo 3 imagenes"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 3
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
