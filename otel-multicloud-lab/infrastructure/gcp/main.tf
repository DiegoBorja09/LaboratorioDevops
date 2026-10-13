locals {
  repository_id   = "otel-multicloud-lab"
  service_name    = "otel-multicloud-lab-service-a"
  collector_image = "us-docker.pkg.dev/cloud-ops-agents-artifacts/google-cloud-opentelemetry-collector/otelcol-google:0.162.0"

  artifact_registry_repository_url = "${var.region}-docker.pkg.dev/${var.project_id}/${local.repository_id}"
  service_a_image                  = "${local.artifact_registry_repository_url}/service-a:${var.service_a_image_tag}"

  labels = {
    project     = "otel-multicloud-lab"
    environment = "university-lab"
  }

  required_services = toset([
    "run.googleapis.com",
    "artifactregistry.googleapis.com",
    "secretmanager.googleapis.com",
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
    "telemetry.googleapis.com",
    "iam.googleapis.com",
  ])
}

resource "google_project_service" "required" {
  for_each = local.required_services

  project                    = var.project_id
  service                    = each.value
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_artifact_registry_repository" "docker" {
  location      = var.region
  repository_id = local.repository_id
  description   = "Imagenes privadas del laboratorio otel-multicloud-lab"
  format        = "DOCKER"
  labels        = local.labels

  cleanup_policy_dry_run = false

  cleanup_policies {
    id     = "delete-old-versions"
    action = "DELETE"
    condition {
      tag_state = "ANY"
    }
  }

  cleanup_policies {
    id     = "keep-most-recent-3"
    action = "KEEP"
    most_recent_versions {
      keep_count = 3
    }
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "collector_config" {
  secret_id = "otel-collector-config"
  labels    = local.labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "collector_config" {
  secret = google_secret_manager_secret.collector_config.id
  secret_data = templatefile("${path.module}/otel-collector-config.yaml", {
    grafana_otlp_endpoint = var.grafana_otlp_endpoint
    grafana_otlp_auth     = var.grafana_otlp_auth
  })
}
