variable "create_instance" {
  description = "false crea solo ECR. true crea la EC2, el rol, el grupo de logs y el grupo de seguridad. Pásalo a true después de publicar la imagen."
  type        = bool
  default     = false
}

variable "aws_region" {
  description = "Región del laboratorio. La cuenta debe tener ahí su VPC predeterminada."
  type        = string
  default     = "us-east-1"

  validation {
    condition     = var.aws_region == "us-east-1"
    error_message = "Este laboratorio se despliega en us-east-1."
  }
}

variable "instance_type" {
  description = "Tipo de la instancia EC2. El valor del laboratorio es t3.small."
  type        = string
  default     = "t3.small"
}

variable "subnet_id" {
  description = "Subred pública de la VPC predeterminada. Null usa la primera subred pública en orden alfabético."
  type        = string
  default     = null
}

variable "service_b_port" {
  description = "Puerto TCP publicado en la instancia para la demostración de service-b."
  type        = number
  default     = 8082

  validation {
    condition     = var.service_b_port == 8082
    error_message = "La demostración publica únicamente el puerto 8082."
  }
}

variable "service_b_image_tag" {
  description = "Etiqueta de la imagen de service-b dentro del repositorio ECR."
  type        = string
  default     = "lab"

  validation {
    condition     = length(trimspace(var.service_b_image_tag)) > 0
    error_message = "La etiqueta de la imagen no puede estar vacía."
  }
}

variable "postgres_user" {
  description = "Usuario que PostgreSQL crea al iniciar. La contraseña no es una variable: la genera random_password."
  type        = string
  default     = "postgres"
}

variable "grafana_otlp_endpoint" {
  description = "URL base OTLP de Grafana Cloud, sin /v1/traces. Obligatoria cuando create_instance es true."
  type        = string
  default     = ""

  validation {
    condition = !var.create_instance || (
      length(trimspace(var.grafana_otlp_endpoint)) > 0 &&
      !strcontains(var.grafana_otlp_endpoint, "example.invalid")
    )
    error_message = "grafana_otlp_endpoint debe ser la URL real de Grafana Cloud cuando create_instance es true."
  }
}

variable "grafana_otlp_auth" {
  description = "Valor completo del header Authorization, por ejemplo Basic seguido del base64. No lo versiones."
  type        = string
  sensitive   = true
  default     = ""

  validation {
    condition = !var.create_instance || (
      length(trimspace(var.grafana_otlp_auth)) > 0 &&
      !strcontains(var.grafana_otlp_auth, "REPLACE_WITH")
    )
    error_message = "grafana_otlp_auth debe ser el header Basic real cuando create_instance es true."
  }
}

variable "postgres_db" {
  description = "Base de datos que service-b migra al arrancar."
  type        = string
  default     = "orders_db"
}
