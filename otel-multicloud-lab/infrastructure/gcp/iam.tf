locals {
  cloud_run_roles = toset([
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
    "roles/secretmanager.secretAccessor",
  ])
}

resource "google_service_account" "cloud_run" {
  account_id   = "otel-lab-service-a"
  display_name = "Cloud Run service-a"
  description  = "Identidad exclusiva del servicio Cloud Run de service-a"
  project      = var.project_id

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "cloud_run" {
  for_each = local.cloud_run_roles

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.cloud_run.email}"
}

data "google_project" "lab" {
  count = var.create_service ? 1 : 0

  project_id = var.project_id
}

resource "google_artifact_registry_repository_iam_member" "cloud_run_agent" {
  count = var.create_service ? 1 : 0

  project    = var.project_id
  location   = google_artifact_registry_repository.docker.location
  repository = google_artifact_registry_repository.docker.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:service-${data.google_project.lab[0].number}@serverless-robot-prod.iam.gserviceaccount.com"

  depends_on = [google_project_service.required]
}
