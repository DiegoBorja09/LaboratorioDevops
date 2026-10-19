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
  count = var.create_service || var.create_data_service || var.create_data_migration_job ? 1 : 0

  project_id = var.project_id
}

resource "google_artifact_registry_repository_iam_member" "cloud_run_agent" {
  count = var.create_service || var.create_data_service || var.create_data_migration_job ? 1 : 0

  project    = var.project_id
  location   = google_artifact_registry_repository.docker.location
  repository = google_artifact_registry_repository.docker.repository_id
  role       = "roles/artifactregistry.reader"
  member     = "serviceAccount:service-${data.google_project.lab[0].number}@serverless-robot-prod.iam.gserviceaccount.com"

  depends_on = [google_project_service.required]
}

locals {
  data_service_roles = toset([
    "roles/cloudsql.client",
    "roles/logging.logWriter",
    "roles/monitoring.metricWriter",
    "roles/cloudtrace.agent",
  ])
}

resource "google_service_account" "data_service" {
  count = var.create_integrator_foundation ? 1 : 0

  account_id   = "otel-lab-data-service"
  display_name = "Cloud Run data-service"
  description  = "Identidad exclusiva de data-service. No administra el proyecto."
  project      = var.project_id

  depends_on = [google_project_service.required]
}

resource "google_project_iam_member" "data_service" {
  for_each = var.create_integrator_foundation ? local.data_service_roles : toset([])

  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.data_service[0].email}"
}

resource "google_secret_manager_secret_iam_member" "data_service_collector" {
  count = var.create_integrator_foundation ? 1 : 0

  project   = var.project_id
  secret_id = google_secret_manager_secret.collector_config.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.data_service[0].email}"
}

resource "google_compute_subnetwork_iam_member" "cloud_run_network_user" {
  count = (var.create_data_service || var.create_data_migration_job) && var.create_integrator_foundation ? 1 : 0

  project    = var.project_id
  region     = var.region
  subnetwork = google_compute_subnetwork.integrator[0].name
  role       = "roles/compute.networkUser"
  member     = "serviceAccount:service-${data.google_project.lab[0].number}@serverless-robot-prod.iam.gserviceaccount.com"
}
