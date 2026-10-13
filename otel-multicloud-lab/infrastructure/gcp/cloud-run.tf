resource "google_cloud_run_v2_service" "service_a" {
  count = var.create_service ? 1 : 0

  name                = local.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.labels

  template {
    service_account                  = google_service_account.cloud_run.email
    timeout                          = "60s"
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"
    max_instance_request_concurrency = 20

    annotations = {
      "otel-collector-config-version" = google_secret_manager_secret_version.collector_config.version
    }

    scaling {
      min_instance_count = 0
      max_instance_count = 1
    }

    volumes {
      name = "collector-config"
      secret {
        secret       = google_secret_manager_secret.collector_config.secret_id
        default_mode = 292
        items {
          version = "latest"
          path    = "config.yaml"
        }
      }
    }

    containers {
      name  = "service-a"
      image = local.service_a_image

      ports {
        container_port = 8080
      }

      resources {
        cpu_idle = true
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      env {
        name  = "OTEL_EXPORTER_OTLP_ENDPOINT"
        value = "http://localhost:4317"
      }

      env {
        name  = "OTEL_METRIC_EXPORT_INTERVAL"
        value = "5000"
      }

      env {
        name  = "SERVICE_B_URL"
        value = var.service_b_url
      }

      env {
        name  = "SERVICE_B_TIMEOUT_SECONDS"
        value = tostring(var.service_b_timeout_seconds)
      }

      env {
        name  = "LOG_LEVEL"
        value = var.log_level
      }

      env {
        name  = "DEPLOYMENT_ENVIRONMENT"
        value = "gcp"
      }

      depends_on = ["collector"]
    }

    containers {
      name  = "collector"
      image = local.collector_image
      args  = ["--config=/etc/otelcol-google/config.yaml"]

      resources {
        cpu_idle = true
        limits = {
          cpu    = "1"
          memory = "512Mi"
        }
      }

      startup_probe {
        timeout_seconds   = 10
        period_seconds    = 30
        failure_threshold = 3
        http_get {
          path = "/"
          port = 13133
        }
      }

      liveness_probe {
        timeout_seconds   = 10
        period_seconds    = 30
        failure_threshold = 3
        http_get {
          path = "/"
          port = 13133
        }
      }

      volume_mounts {
        name       = "collector-config"
        mount_path = "/etc/otelcol-google"
      }
    }
  }

  depends_on = [
    google_project_service.required,
    google_project_iam_member.cloud_run,
    google_secret_manager_secret_version.collector_config,
    google_artifact_registry_repository_iam_member.cloud_run_agent,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "public" {
  count = var.create_service ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.service_a[0].location
  name     = google_cloud_run_v2_service.service_a[0].name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
