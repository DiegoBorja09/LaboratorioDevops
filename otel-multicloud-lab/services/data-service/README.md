# data-service

Microservicio de auditoría. Recibe un evento desde service-a y lo escribe en dos bases PostgreSQL independientes: Cloud SQL y AWS RDS. Exporta trazas, métricas y logs por OTLP.

```mermaid
flowchart LR
  serviceA[service-a] --> serviceB[service-b]
  serviceA --> dataService[data-service]
  dataService --> cloudSql[GCP Cloud SQL]
  dataService --> rds[AWS RDS]
```

## Limitación del dual-write

No hay transacción distribuida. service-a llama a data-service solo después de que service-b guardó la orden. data-service escribe primero en Cloud SQL y después en RDS. Si RDS falla, Cloud SQL ya tiene el evento y la respuesta es `503`. Un reintento con el mismo `event_id` no duplica la fila existente y completa el lado que faltaba. Si Cloud SQL falla, RDS no se toca.

Si data-service no responde, service-a devuelve `502` o `504` y no vuelve a crear la orden en service-b. La orden ya creada permanece.

## Variables

Ninguna URL ni contraseña de Cloud SQL o RDS se versiona. En Compose las dos conexiones apuntan al PostgreSQL local del laboratorio.

| Variable | Uso | Valor local |
| --- | --- | --- |
| `GCP_DATABASE_URL` | SQLAlchemy async hacia Cloud SQL | `postgresql+asyncpg://postgres:postgres@postgres:5432/orders_db` |
| `AWS_DATABASE_URL` | SQLAlchemy async hacia RDS | la misma URL local |
| `OTEL_DEPLOYMENT_ENVIRONMENT` | `deployment.environment` | `local` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Collector OTLP gRPC | `http://otel-collector:4317` |
| `OTEL_SDK_DISABLED` | Apaga el SDK en las pruebas | `true` en Pytest |
| `CHAOS_ENABLED` | Caos al arrancar | `false` |
| `CHAOS_ERROR_RATE` | Probabilidad de 0 a 1 | `0` |
| `CHAOS_DELAY_MS` | Espera antes de escribir | `0` |
| `CHAOS_TOKEN` | Valor esperado de `X-Chaos-Token` | vacío |

El recurso OpenTelemetry queda fijo: `service.name=data-service`, `service.namespace=otel-multicloud-lab` y `service.version=1.0.0`.

## Endpoints

| Método | Ruta | Resultado |
| --- | --- | --- |
| `GET` | `/health` | `200`. No consulta bases. |
| `GET` | `/ready` | `SELECT 1` en cada base. `200` si ambas responden y `503` si alguna falla. El cuerpo indica `gcp` y `aws`. |
| `POST` | `/api/v1/data/replicate` | Inserta el evento en ambas. `201` si las dos escrituras terminan. `503` si el caos o una base fallan. |
| `POST` | `/internal/chaos` | Activa un fallo temporal. Exige `X-Chaos-Token`. No devuelve el token. |

Cuerpo de replicación:

```json
{
  "event_id": "33333333-3333-3333-3333-333333333333",
  "order_id": "22222222-2222-2222-2222-222222222222",
  "source_service": "service-a",
  "status": "created"
}
```

`event_id` es la clave primaria. Repetir el mismo valor responde `201` con `duplicate` en el lado que ya existía.

El caos acepta `error_rate` entre 0 y 1, `delay_ms` y `duration_seconds` como máximo 600. El fallo ocurre antes de escribir, así que no deja una réplica parcial. Al cumplirse `duration_seconds` vuelve al estado de las variables de entorno.

## Métricas

| Nombre | Tipo | Atributos |
| --- | --- | --- |
| `app.data_service.requests` | Counter | `result=success\|error`, `operation=replicate\|ready` |
| `app.data_service.request.duration` | Histogram, segundos | `operation`, `result` |
| `app.data_service.database.operations` | Counter | `cloud=gcp\|aws`, `operation=insert\|select`, `result` |
| `app.data_service.replication.failures` | Counter | `cloud` |
| `app.data_service.chaos.injections` | Counter | `operation=replicate` |

Los logs JSON incluyen `trace_id` y `span_id` del span activo. No incluyen contraseñas ni la URL completa. Un fallo inyectado registra `chaos.injected_error`.

Los spans de base usan `db.system.name`, `db.namespace`, `db.operation.name`, `server.address` y `server.port`. No llevan el texto SQL ni credenciales.

## Ejecución local

Desde `otel-multicloud-lab`:

```powershell
docker compose up --build data-service
curl.exe http://localhost:8083/health
```

El contenedor escucha en `0.0.0.0:8080`. Compose publica el puerto 8083.

`DATA_SERVICE_SKIP_MIGRATIONS=true` arranca la API sin ejecutar Alembic. El valor por defecto es `false`: el entrypoint migra primero Cloud SQL y después RDS, y se puede repetir. En Cloud Run el servicio lleva el salto activado; el Cloud Run Job no, así que las migraciones no ocurren durante `terraform apply`.

Pruebas, sin bases reales:

```powershell
Set-Location services/data-service
$env:OTEL_SDK_DISABLED = "true"
python -m pytest
```

Imagen:

```powershell
docker build --tag otel-multicloud-lab-data-service:ci services/data-service
```
