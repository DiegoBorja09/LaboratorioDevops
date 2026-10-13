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
