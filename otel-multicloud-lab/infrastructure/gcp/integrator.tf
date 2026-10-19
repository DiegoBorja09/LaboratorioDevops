locals {
  integrator_enabled = var.create_integrator_foundation
  integrator_labels = merge(local.labels, {
    component = "integrator"
  })
}

resource "google_project_service" "integrator" {
  for_each = local.integrator_enabled ? toset([
    "compute.googleapis.com",
    "sqladmin.googleapis.com",
  ]) : toset([])

  project                    = var.project_id
  service                    = each.value
  disable_on_destroy         = false
  disable_dependent_services = false
}

resource "google_compute_network" "integrator" {
  count = local.integrator_enabled ? 1 : 0

  name                    = "otel-lab-integrator"
  project                 = var.project_id
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"

  depends_on = [google_project_service.integrator]
}

resource "google_compute_subnetwork" "integrator" {
  count = local.integrator_enabled ? 1 : 0

  name                     = "otel-lab-integrator"
  project                  = var.project_id
  region                   = var.region
  network                  = google_compute_network.integrator[0].id
  ip_cidr_range            = local.integrator_subnet_cidr
  private_ip_google_access = true

  # 10.80.0.0/24 no pisa la red default de GCP (10.128.0.0/20 en us-east1) ni la VPC default de AWS (172.31.0.0/16).
  log_config {
    aggregation_interval = "INTERVAL_30_SEC"
    flow_sampling        = 0.5
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_router" "integrator" {
  count = local.integrator_enabled ? 1 : 0

  name    = "otel-lab-integrator"
  project = var.project_id
  region  = var.region
  network = google_compute_network.integrator[0].id
}

resource "google_compute_address" "integrator_nat" {
  count = local.integrator_enabled ? 1 : 0

  name         = "otel-lab-integrator-nat"
  project      = var.project_id
  region       = var.region
  address_type = "EXTERNAL"
  network_tier = "PREMIUM"
  labels       = local.integrator_labels

  depends_on = [google_project_service.integrator]
}

resource "google_compute_router_nat" "integrator" {
  count = local.integrator_enabled ? 1 : 0

  name                               = "otel-lab-integrator"
  project                            = var.project_id
  region                             = var.region
  router                             = google_compute_router.integrator[0].name
  nat_ip_allocate_option             = "MANUAL_ONLY"
  nat_ips                            = [google_compute_address.integrator_nat[0].self_link]
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.integrator[0].id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }
}

resource "google_sql_database_instance" "integrator" {
  count = local.integrator_enabled ? 1 : 0

  name                = "otel-lab-integrator"
  project             = var.project_id
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = false

  settings {
    tier              = "db-f1-micro"
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_SSD"
    disk_size         = 10
    disk_autoresize   = false
    pricing_plan      = "PER_USE"
    activation_policy = "ALWAYS"
    user_labels       = local.integrator_labels

    backup_configuration {
      enabled                        = false
      point_in_time_recovery_enabled = false
    }

    ip_configuration {
      ipv4_enabled = true
      ssl_mode     = "ENCRYPTED_ONLY"
    }

    maintenance_window {
      day  = 7
      hour = 3
    }
  }

  depends_on = [google_project_service.integrator]
}

resource "google_sql_database" "integrator" {
  count = local.integrator_enabled ? 1 : 0

  name     = "otel_integrator"
  project  = var.project_id
  instance = google_sql_database_instance.integrator[0].name
}

resource "random_password" "cloudsql" {
  count = local.integrator_enabled ? 1 : 0

  length      = 32
  special     = false
  min_lower   = 1
  min_upper   = 1
  min_numeric = 1
}

resource "google_sql_user" "data_service" {
  count = local.integrator_enabled ? 1 : 0

  name     = "data_service"
  project  = var.project_id
  instance = google_sql_database_instance.integrator[0].name
  password = random_password.cloudsql[0].result
}

resource "random_password" "chaos_token" {
  count = local.integrator_enabled ? 1 : 0

  length      = 32
  special     = false
  min_lower   = 1
  min_upper   = 1
  min_numeric = 1
}

resource "google_secret_manager_secret" "gcp_database_url" {
  count = local.integrator_enabled ? 1 : 0

  secret_id = "data-service-gcp-database-url"
  project   = var.project_id
  labels    = local.integrator_labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "gcp_database_url" {
  count = local.integrator_enabled ? 1 : 0

  secret = google_secret_manager_secret.gcp_database_url[0].id
  secret_data = format(
    "postgresql+asyncpg://%s:%s@/%s?host=/cloudsql/%s",
    urlencode(google_sql_user.data_service[0].name),
    urlencode(random_password.cloudsql[0].result),
    google_sql_database.integrator[0].name,
    google_sql_database_instance.integrator[0].connection_name,
  )
}

resource "google_secret_manager_secret" "aws_database_url" {
  count = local.integrator_enabled ? 1 : 0

  secret_id = "data-service-aws-database-url"
  project   = var.project_id
  labels    = local.integrator_labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret" "chaos_token" {
  count = local.integrator_enabled ? 1 : 0

  secret_id = "data-service-chaos-token"
  project   = var.project_id
  labels    = local.integrator_labels

  replication {
    auto {}
  }

  depends_on = [google_project_service.required]
}

resource "google_secret_manager_secret_version" "chaos_token" {
  count = local.integrator_enabled ? 1 : 0

  secret      = google_secret_manager_secret.chaos_token[0].id
  secret_data = random_password.chaos_token[0].result
}

resource "google_secret_manager_secret_iam_member" "data_service_gcp_database_url" {
  count = local.integrator_enabled ? 1 : 0

  project   = var.project_id
  secret_id = google_secret_manager_secret.gcp_database_url[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.data_service[0].email}"
}

resource "google_secret_manager_secret_iam_member" "data_service_aws_database_url" {
  count = local.integrator_enabled ? 1 : 0

  project   = var.project_id
  secret_id = google_secret_manager_secret.aws_database_url[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.data_service[0].email}"
}

resource "google_secret_manager_secret_iam_member" "data_service_chaos_token" {
  count = local.integrator_enabled ? 1 : 0

  project   = var.project_id
  secret_id = google_secret_manager_secret.chaos_token[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.data_service[0].email}"
}

data "google_secret_manager_secret_version" "aws_database_url" {
  count = (var.create_data_service || var.create_data_migration_job) && local.integrator_enabled ? 1 : 0

  project = var.project_id
  secret  = google_secret_manager_secret.aws_database_url[0].secret_id
}
