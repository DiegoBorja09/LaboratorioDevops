output "ecr_repository_url" {
  description = "URL del repositorio ECR privado de service-b, sin etiqueta."
  value       = aws_ecr_repository.service_b.repository_url
}

output "ec2_instance_id" {
  description = "ID de la instancia EC2. Null mientras create_instance es false."
  value       = one(aws_instance.lab[*].id)
}

output "service_b_public_ip" {
  description = "IPv4 pública automática de la subred. No es una Elastic IP y cambia si la instancia se detiene."
  value       = one(aws_instance.lab[*].public_ip)
}

output "service_b_health_url" {
  description = "Comprobación HTTP de service-b, incluido el estado de PostgreSQL."
  value = one([
    for ip in aws_instance.lab[*].public_ip : "http://${ip}:${var.service_b_port}/health"
  ])
}
