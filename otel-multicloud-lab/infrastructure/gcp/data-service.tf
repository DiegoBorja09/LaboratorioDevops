locals {
  deploy_data_service  = var.create_data_service && var.create_integrator_foundation
  deploy_migration_job = var.create_data_migration_job && var.create_integrator_foundation
}

resource "google_cloud_run_v2_service" "data_service" {
  count = local.deploy_data_service ? 1 : 0

  name                = "otel-multicloud-lab-data-service"
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false
  labels              = local.integrator_labels

  template {
    service_account                  = google_service_account.data_service[0].email
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

    vpc_access {
      egress = "ALL_TRAFFIC"
      network_interfaces {
        network    = google_compute_network.integrator[0].id
        subnetwork = google_compute_subnetwork.integrator[0].id
      }
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

    volumes {
      name = "cloudsql"
      cloud_sql_instance {
        instances = [google_sql_database_instance.integrator[0].connection_name]
      }
    }

    containers {
      name  = "data-service"
      image = local.data_service_image

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
        name  = "OTEL_SERVICE_NAME"
        value = "data-service"
      }

      env {
        name  = "OTEL_DEPLOYMENT_ENVIRONMENT"
        value = "university-lab"
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
        name  = "LOG_LEVEL"
        value = "INFO"
      }

      env {
        name  = "DATA_SERVICE_SKIP_MIGRATIONS"
        value = "true"
      }

      env {
        name  = "CHAOS_ENABLED"
        value = "false"
      }

      env {
        name  = "CHAOS_ERROR_RATE"
        value = "0"
      }

      env {
        name  = "CHAOS_DELAY_MS"
        value = "0"
      }

      env {
        name = "GCP_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.gcp_database_url[0].secret_id
            version = google_secret_manager_secret_version.gcp_database_url[0].version
          }
        }
      }

      env {
        name = "AWS_DATABASE_URL"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.aws_database_url[0].secret_id
            version = data.google_secret_manager_secret_version.aws_database_url[0].version
          }
        }
      }

      env {
        name = "CHAOS_TOKEN"
        value_source {
          secret_key_ref {
            secret  = google_secret_manager_secret.chaos_token[0].secret_id
            version = google_secret_manager_secret_version.chaos_token[0].version
          }
        }
      }

      volume_mounts {
        name       = "cloudsql"
        mount_path = "/cloudsql"
      }

      startup_probe {
        timeout_seconds   = 10
        period_seconds    = 30
        failure_threshold = 3
        http_get {
          path = "/health"
          port = 8080
        }
      }

      liveness_probe {
        timeout_seconds   = 10
        period_seconds    = 30
        failure_threshold = 3
        http_get {
          path = "/health"
          port = 8080
        }
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
    google_project_iam_member.data_service,
    google_secret_manager_secret_iam_member.data_service_gcp_database_url,
    google_secret_manager_secret_iam_member.data_service_aws_database_url,
    google_secret_manager_secret_iam_member.data_service_chaos_token,
    google_secret_manager_secret_iam_member.data_service_collector,
    google_secret_manager_secret_version.collector_config,
    google_compute_router_nat.integrator,
    google_compute_subnetwork_iam_member.cloud_run_network_user,
    google_artifact_registry_repository_iam_member.cloud_run_agent,
  ]
}

resource "google_cloud_run_v2_service_iam_member" "data_service_invoker" {
  count = local.deploy_data_service ? 1 : 0

  project  = var.project_id
  location = google_cloud_run_v2_service.data_service[0].location
  name     = google_cloud_run_v2_service.data_service[0].name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.cloud_run.email}"
}

resource "google_cloud_run_v2_job" "data_migration" {
  count = local.deploy_migration_job ? 1 : 0

  name                = "otel-multicloud-lab-data-migrate"
  location            = var.region
  deletion_protection = false
  labels              = local.integrator_labels

  template {
    template {
      service_account       = google_service_account.data_service[0].email
      timeout               = "600s"
      max_retries           = 0
      execution_environment = "EXECUTION_ENVIRONMENT_GEN2"

      vpc_access {
        egress = "ALL_TRAFFIC"
        network_interfaces {
          network    = google_compute_network.integrator[0].id
          subnetwork = google_compute_subnetwork.integrator[0].id
        }
      }

      volumes {
        name = "cloudsql"
        cloud_sql_instance {
          instances = [google_sql_database_instance.integrator[0].connection_name]
        }
      }

      containers {
        image = local.data_service_image
        args  = ["python", "-c", "import sys; sys.exit(0)"]

        resources {
          limits = {
            cpu    = "1"
            memory = "512Mi"
          }
        }

        env {
          name  = "LOG_LEVEL"
          value = "INFO"
        }

        env {
          name = "GCP_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.gcp_database_url[0].secret_id
              version = google_secret_manager_secret_version.gcp_database_url[0].version
            }
          }
        }

        env {
          name = "AWS_DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.aws_database_url[0].secret_id
              version = data.google_secret_manager_secret_version.aws_database_url[0].version
            }
          }
        }

        volume_mounts {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
    }
  }

  depends_on = [
    google_project_iam_member.data_service,
    google_secret_manager_secret_iam_member.data_service_gcp_database_url,
    google_secret_manager_secret_iam_member.data_service_aws_database_url,
    google_compute_router_nat.integrator,
    google_compute_subnetwork_iam_member.cloud_run_network_user,
  ]
}
