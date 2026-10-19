variable "project_id" {
  description = "ID del proyecto GCP. El laboratorio usa otel-multicloud-lab-75147."
  type        = string

  validation {
    condition     = length(trimspace(var.project_id)) > 0
    error_message = "project_id no puede estar vacío."
  }
}

variable "region" {
  description = "Región de Artifact Registry y Cloud Run. us-east1 queda junto a service-b en AWS us-east-1."
  type        = string
  default     = "us-east1"

  validation {
    condition     = var.region == "us-east1"
    error_message = "Este laboratorio se despliega en us-east1."
  }
}

variable "create_service" {
  description = "false crea APIs, Artifact Registry, la cuenta de servicio y el secreto. true agrega Cloud Run."
  type        = bool
  default     = false
}

variable "service_a_image_tag" {
  description = "Etiqueta de la imagen de service-a en Artifact Registry."
  type        = string
  default     = "lab"

  validation {
    condition     = length(trimspace(var.service_a_image_tag)) > 0
    error_message = "La etiqueta de la imagen no puede estar vacía."
  }
}

variable "service_b_url" {
  description = "URL pública de service-b. Obligatoria solo cuando create_service es true."
  type        = string
  default     = ""

  validation {
    condition     = !var.create_service || length(trimspace(var.service_b_url)) > 0
    error_message = "service_b_url es obligatorio cuando create_service es true."
  }
}

variable "service_b_timeout_seconds" {
  description = "Timeout HTTP de service-a hacia service-b, en segundos."
  type        = number
  default     = 5

  validation {
    condition     = var.service_b_timeout_seconds > 0
    error_message = "service_b_timeout_seconds debe ser mayor que cero."
  }
}

variable "grafana_otlp_endpoint" {
  description = "URL base OTLP de Grafana Cloud, sin /v1/traces. Obligatoria cuando create_service es true."
  type        = string
  default     = ""

  validation {
    condition = !(var.create_service || var.create_data_service || var.create_data_migration_job) || (
      length(trimspace(var.grafana_otlp_endpoint)) > 0 &&
      !strcontains(var.grafana_otlp_endpoint, "example.invalid")
    )
    error_message = "grafana_otlp_endpoint debe ser la URL real de Grafana Cloud cuando se crea un Cloud Run con collector."
  }
}

variable "grafana_otlp_auth" {
  description = "Valor completo del header Authorization, por ejemplo Basic seguido del base64. No lo versiones."
  type        = string
  sensitive   = true
  default     = ""

  validation {
    condition = !(var.create_service || var.create_data_service || var.create_data_migration_job) || (
      length(trimspace(var.grafana_otlp_auth)) > 0 &&
      !strcontains(var.grafana_otlp_auth, "REPLACE_WITH")
    )
    error_message = "grafana_otlp_auth debe ser el header Basic real cuando se crea un Cloud Run con collector."
  }
}

variable "log_level" {
  description = "Nivel de log de service-a."
  type        = string
  default     = "INFO"

  validation {
    condition     = contains(["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"], var.log_level)
    error_message = "log_level debe ser DEBUG, INFO, WARNING, ERROR o CRITICAL."
  }
}

variable "create_integrator_foundation" {
  description = "false no crea red, Cloud SQL ni secretos de data-service. true crea esa fundación y deja Cloud Run apagado."
  type        = bool
  default     = false
}

variable "create_data_service" {
  description = "true crea el Cloud Run privado de data-service. Requiere la fundación, la imagen publicada y la versión del secreto de RDS."
  type        = bool
  default     = false

  validation {
    condition     = !var.create_data_service || var.create_integrator_foundation
    error_message = "create_data_service requiere create_integrator_foundation."
  }
}

variable "create_data_migration_job" {
  description = "true crea el Cloud Run Job de Alembic. El apply no lo ejecuta."
  type        = bool
  default     = false

  validation {
    condition     = !var.create_data_migration_job || var.create_integrator_foundation
    error_message = "create_data_migration_job requiere create_integrator_foundation."
  }
}

variable "data_service_image_tag" {
  description = "Etiqueta de data-service en el Artifact Registry existente."
  type        = string
  default     = "lab"

  validation {
    condition     = length(trimspace(var.data_service_image_tag)) > 0
    error_message = "La etiqueta de data-service no puede estar vacía."
  }
}
