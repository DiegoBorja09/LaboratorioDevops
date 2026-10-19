output "artifact_registry_repository_url" {
  description = "Host y repositorio Docker privado, sin imagen ni etiqueta."
  value       = local.artifact_registry_repository_url
}

output "service_a_image_url" {
  description = "Imagen de service-a que Cloud Run descarga en la fase 2."
  value       = local.service_a_image
}

output "service_a_url" {
  description = "URL HTTPS del servicio. Null mientras create_service es false."
  value       = one(google_cloud_run_v2_service.service_a[*].uri)
}

output "service_account_email" {
  description = "Cuenta de servicio exclusiva de Cloud Run."
  value       = google_service_account.cloud_run.email
}

output "data_service_image_url" {
  description = "Imagen de data-service en el Artifact Registry existente. No se publica desde Terraform."
  value       = local.data_service_image
}

output "integrator_vpc_name" {
  description = "VPC dedicada del integrador. Null mientras create_integrator_foundation es false."
  value       = one(google_compute_network.integrator[*].name)
}

output "integrator_subnet_name" {
  description = "Subred regional us-east1 del integrador."
  value       = one(google_compute_subnetwork.integrator[*].name)
}

output "cloud_run_egress_ip" {
  description = "IPv4 estática de Cloud NAT."
  value       = one(google_compute_address.integrator_nat[*].address)
}

output "cloud_run_egress_cidr" {
  description = "La misma IP de Cloud NAT en formato /32, para el Security Group de RDS."
  value = one([
    for address in google_compute_address.integrator_nat[*].address : "${address}/32"
  ])
}

output "data_service_url" {
  description = "URL HTTPS de data-service. Null mientras create_data_service es false. No es pública sin autenticación."
  value       = one(google_cloud_run_v2_service.data_service[*].uri)
}

output "data_service_account_email" {
  description = "Cuenta otel-lab-data-service. Null mientras la fundación está apagada."
  value       = one(google_service_account.data_service[*].email)
}

output "data_migration_job_name" {
  description = "Nombre del Cloud Run Job de Alembic. Null mientras create_data_migration_job es false."
  value       = one(google_cloud_run_v2_job.data_migration[*].name)
}
