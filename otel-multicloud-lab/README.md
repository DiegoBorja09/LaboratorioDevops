# otel-multicloud-lab

Laboratorio académico de observabilidad. La aplicación base sigue igual: service-a, service-b y PostgreSQL. Ambos servicios exportan trazas, métricas y logs por OTLP hacia un OpenTelemetry Collector. Jaeger recibe las trazas, Prometheus consulta las métricas, Loki guarda los logs y Grafana muestra el dashboard y Explore.

## 1. Requisitos

- Docker y Docker Compose v2
- Python 3.12, solo si vas a ejecutar las pruebas fuera de Docker
- curl

El Collector local vive en `collector/`. Prometheus, Loki y Grafana viven en `monitoring/`. Las pruebas de carga están en `load-tests/` y la documentación en `docs/`. `infrastructure/aws` e `infrastructure/gcp` no declaran recursos: solo permiten que el pipeline compruebe el formato y la sintaxis. Las capturas van en `evidence/`.

## 2. Arquitectura y flujo de la solicitud

```text
Cliente → service-a → HTTP → service-b → PostgreSQL
```

1. El cliente llama a `POST /api/v1/orders` en service-a (puerto local 8081).
2. service-a valida el cuerpo con Pydantic, ejecuta `validate_order` y reenvía la orden con HTTPX, en un solo intento, a `POST /api/v1/orders/process`.
3. service-b ejecuta `process_order`, guarda la fila en la tabla `orders` y responde `201`.
4. service-a devuelve al cliente el resultado de service-b.

El header `X-Request-ID` viaja en la petición y en la respuesta. Si el cliente no lo envía, service-a genera un UUID. Los logs de consola siguen siendo JSON e incluyen `request_id`, método, ruta, código de estado y duración cuando esos datos existen. El `trace_id` y el `span_id` no se imprimen en esa línea de consola: OpenTelemetry los toma del span activo y Loki los guarda como etiquetas.

Los errores HTTP usan esta forma y no incluyen stack traces, credenciales ni la cadena de conexión:

```json
{
  "error": {
    "code": "SERVICE_B_UNAVAILABLE",
    "message": "No fue posible comunicarse con service-b",
    "request_id": "11111111-1111-1111-1111-111111111111"
  }
}
```

Un fallo de conexión hacia service-b responde `502`. Un timeout responde `504`.

## 3. Variables de entorno

Copia el ejemplo si quieres ejecutar los servicios fuera de Compose:

```powershell
Copy-Item .env.example .env
```

| Variable | Uso | Valor en Compose |
| --- | --- | --- |
| `SERVICE_B_URL` | URL base de service-b | `http://service-b:8080` |
| `SERVICE_B_TIMEOUT_SECONDS` | Timeout HTTP de service-a | `5` |
| `DATABASE_URL` | Conexión async de service-b | `postgresql+asyncpg://postgres:postgres@postgres:5432/orders_db` |
| `SERVICE_NAME` | Nombre que aparece en los logs | `service-a` o `service-b` |
| `LOG_LEVEL` | Nivel del logger | `INFO` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | Inicialización de PostgreSQL | `postgres` / `postgres` / `orders_db` |
| `OTEL_SERVICE_NAME` | Nombre del servicio en las trazas | `service-a` o `service-b` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | Collector OTLP gRPC | `http://otel-collector:4317` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | Protocolo del exportador | `grpc` |
| `OTEL_RESOURCE_ATTRIBUTES` | Atributos del recurso, compartidos por trazas y métricas | `service.version=1.0.0,deployment.environment=local,service.namespace=otel-multicloud-lab` |
| `OTEL_METRIC_EXPORT_INTERVAL` | Intervalo de exportación de métricas, en milisegundos | `5000` |
| `OTEL_SDK_DISABLED` | Apaga por completo el SDK y la instrumentación | `false` en el laboratorio; `true` en Pytest y en el baseline |
| `GRAFANA_ADMIN_USER` | Usuario inicial de Grafana | `admin` |
| `GRAFANA_ADMIN_PASSWORD` | Contraseña inicial de Grafana | `admin` |

Esas credenciales son solo del laboratorio local. No las reutilices en otro entorno. Compose ya las define, así que `docker compose up --build` no depende de un archivo `.env`.

## 4. Ejecutar con Docker Compose

Desde la raíz del repositorio:

```powershell
docker compose up --build
```

Puertos locales:

| Servicio | URL |
| --- | --- |
| service-a | http://localhost:8081 |
| service-b | http://localhost:8082 |
| PostgreSQL | `localhost:5433` |
| Jaeger | http://localhost:16686 |
| Prometheus | http://localhost:9090 |
| Grafana | http://localhost:3000 |
| Loki | http://localhost:3100 |
| OTel Collector gRPC | `localhost:4317` |
| OTel Collector HTTP | `localhost:4318` |
| Salud del Collector | http://localhost:13133 |

service-b espera a que PostgreSQL esté saludable, aplica las migraciones y después arranca Uvicorn. service-a espera a que service-b esté saludable.

## 5. Migraciones

La migración inicial crea la tabla `orders` (`id`, `customer_id`, `amount`, `currency`, `status`, `request_id`, `created_at`).

Al iniciar el contenedor de service-b, `entrypoint.py` ejecuta:

```text
alembic upgrade head
```

y luego Uvicorn. En un volumen nuevo no hay que lanzar la migración a mano.

Para repetirla dentro del contenedor que ya está en ejecución:

```powershell
docker compose exec service-b alembic upgrade head
```

Desde el host, con el virtualenv del apartado de pruebas y PostgreSQL publicado en el puerto 5433:

```powershell
$env:DATABASE_URL = "postgresql+asyncpg://postgres:postgres@localhost:5433/orders_db"
Set-Location services/service-b
alembic upgrade head
Set-Location ../..
```

## 6. Pruebas

Las pruebas de service-a simulan HTTPX con `MockTransport` y no necesitan a service-b. Las de service-b usan SQLite en un archivo temporal, de modo que no hace falta levantar PostgreSQL para `pytest`. El esquema de PostgreSQL se comprueba al arrancar Compose, que aplica Alembic sobre una base vacía.

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r services/service-a/requirements-dev.txt
python -m pip install -r services/service-b/requirements-dev.txt
Set-Location services/service-a
python -m pytest
Set-Location ../service-b
python -m pytest
Set-Location ../..
```

En bash el equivalente es `python3.12 -m venv .venv`, `source .venv/bin/activate` y `cd` en lugar de `Set-Location`.

## 7. Ejemplos curl

En PowerShell usa `curl.exe`. `curl` a secas es un alias de `Invoke-WebRequest`.

Salud de cada servicio:

```powershell
curl.exe http://localhost:8081/health
curl.exe http://localhost:8082/health
```

Crear una orden desde PowerShell. El cuerpo va por la entrada estándar para que las comillas del JSON no se alteren. `currency` llega en minúsculas y la API lo guarda como `COP`:

```powershell
@'
{"customer_id":"customer-001","amount":150000.50,"currency":"cop"}
'@ | curl.exe -sS -X POST http://localhost:8081/api/v1/orders `
  -H "Content-Type: application/json" `
  -H "X-Request-ID: 11111111-1111-1111-1111-111111111111" `
  --data-binary "@-"
```

El mismo llamado en bash:

```bash
curl -sS -X POST http://localhost:8081/api/v1/orders \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: 11111111-1111-1111-1111-111111111111" \
  -d '{"customer_id":"customer-001","amount":150000.50,"currency":"cop"}'
```

Consulta la orden con el `id` devuelto:

```powershell
curl.exe http://localhost:8082/api/v1/orders/UUID-DE-LA-ORDEN
```

También puedes crearla directo en service-b, con el mismo cuerpo y el mismo header:

```powershell
@'
{"customer_id":"customer-001","amount":150000.50,"currency":"cop"}
'@ | curl.exe -sS -X POST http://localhost:8082/api/v1/orders/process `
  -H "Content-Type: application/json" `
  -H "X-Request-ID: 11111111-1111-1111-1111-111111111111" `
  --data-binary "@-"
```

Logs JSON de una petición:

```powershell
docker compose logs --tail 50 service-a service-b
```

## 8. Trazas distribuidas

service-a y service-b exportan trazas por OTLP gRPC al mismo Collector. HTTPX inyecta el header W3C `traceparent` en la llamada hacia service-b, y FastAPI lo extrae al recibir la petición. service-b no crea un `trace_id` nuevo: el span servidor continúa la traza que llegó desde service-a. `X-Request-ID` se sigue enviando junto con `traceparent`.

El `trace_id` identifica toda la operación, desde el `POST` del cliente hasta PostgreSQL. El `span_id` identifica cada tramo dentro de esa operación. Los spans de una misma orden comparten el `trace_id` y tienen `span_id` distintos. El span servidor de service-b es hijo del span cliente HTTPX de service-a.

SQLAlchemy asíncrono se instrumenta sobre el `sync_engine` del engine que ya usa service-b. Eso produce spans de `INSERT` y `SELECT`. No se instrumenta asyncpg aparte, para no duplicar la misma consulta. Las migraciones de Alembic corren en otro proceso, antes de arrancar la API, y no pasan por esta instrumentación. `GET /health` no genera trazas.

```mermaid
flowchart LR
    cliente[Cliente] --> serviceA[service-a]
    serviceA -->|HTTP y traceparent| serviceB[service-b]
    serviceB --> postgres[PostgreSQL]
    serviceA -->|OTLP gRPC| collector[OTel Collector]
    serviceB -->|OTLP gRPC| collector
    collector -->|OTLP gRPC| jaeger[Jaeger]
    collector -->|Prometheus 8889| prometheus[Prometheus]
    prometheus --> grafana[Grafana]
    collector -->|OTLP HTTP| loki[Loki]
    loki --> grafana
```

Jerarquía esperada de `POST /api/v1/orders`:

1. `POST /api/v1/orders`, service-a, servidor.
2. `validate_order`, service-a.
3. Llamada HTTPX a service-b, service-a, cliente.
4. `POST /api/v1/orders/process`, service-b, servidor.
5. `process_order`, service-b.
6. `INSERT` de SQLAlchemy hacia PostgreSQL, service-b.

SQLAlchemy puede añadir spans de conexión, transacción o commit. No debe haber dos spans idénticos para la misma consulta. Los spans no incluyen `customer_id`, el monto, el cuerpo de la petición ni la contraseña de la base.

Si el Collector no está disponible, los dos servicios arrancan y procesan órdenes igual. Los logs de consola se siguen escribiendo aunque Loki no reciba la copia OTLP.

Para ver una traza:

```powershell
docker compose up -d --build
docker compose ps
docker compose logs service-b --tail=100
docker compose logs otel-collector --tail=100
```

Crea una orden con el `POST` de la sección anterior y abre http://localhost:16686. En Jaeger elige el servicio `service-a`, pulsa Find Traces y abre la traza del `POST /api/v1/orders`. En el detalle deben aparecer service-a y service-b, los spans HTTP, `process_order` y el span de PostgreSQL. Una captura de referencia está en `evidence/traces/02-distributed-trace-service-a-service-b-db.png`.

## 9. Métricas

service-a y service-b exportan métricas por el mismo OTLP gRPC que las trazas. El Collector las publica en `otel-collector:8889` y Prometheus las consulta cada 5 segundos. Las métricas internas del Collector salen por el puerto 8888. Jaeger no recibe métricas.

```powershell
docker compose up -d --build
```

Prometheus queda en http://localhost:9090. Para generar tráfico:

```powershell
1..10 | ForEach-Object {
  @'
{"customer_id":"customer-001","amount":150000.50,"currency":"cop"}
'@ | curl.exe -sS -o NUL -w "%{http_code}`n" -X POST http://localhost:8081/api/v1/orders `
    -H "Content-Type: application/json" `
    --data-binary "@-"
}
@'
{"customer_id":"customer-001","amount":150000.50,"currency":"x"}
'@ | curl.exe -sS -o NUL -w "%{http_code}`n" -X POST http://localhost:8081/api/v1/orders `
  -H "Content-Type: application/json" `
  --data-binary "@-"
```

Espera unos segundos, porque el SDK exporta cada 5 segundos y Prometheus tarda otro scrape. En http://localhost:9090/graph ejecuta, por ejemplo:

```promql
app_orders_requests_total{service_name="service-a"}
app_orders_errors_total{service_name="service-a"}
app_orders_duration_seconds_bucket{service_name="service-a"}
app_orders_in_flight{service_name="service-a"}
app_orders_processed_total{service_name="service-b"}
app_orders_processing_errors_total{service_name="service-b"}
app_orders_processing_duration_seconds_bucket{service_name="service-b"}
up
```

Esos son los nombres que publica el exporter de esta versión: los puntos pasan a guiones bajos, la unidad `s` se vuelve `_seconds` y los contadores ganan el sufijo `_total`. `trace_id` no aparece como etiqueta. Para listar todos los nombres:

```powershell
curl.exe -sS "http://localhost:9090/api/v1/label/__name__/values"
```

`service_name="service-a"` y `service_name="service-b"` confirman que ambos servicios exportan. `up{job="otel-collector"}` y `up{job="otel-collector-internal"}` confirman que Prometheus llega al Collector.

Además de las métricas de negocio, cada servicio publica `process.cpu.utilization` y `process.memory.usage` con el mismo `MeterProvider` y el mismo exportador OTLP. En Prometheus la CPU aparece como `process_cpu_utilization_ratio`, con valor entre 0 y 1, y la memoria como `process_memory_usage_bytes`.

## 10. Grafana

Grafana OSS 12.4.3 está en http://localhost:3000. En este laboratorio el usuario y la contraseña iniciales son `admin` / `admin`, definidos por `GRAFANA_ADMIN_USER` y `GRAFANA_ADMIN_PASSWORD`. Cámbialos en cualquier ambiente que no sea local. El data source `Prometheus` apunta a `http://prometheus:9090` y el data source `Loki` apunta a `http://loki:3100`, ambos dentro de la red de Compose. Ninguno se puede editar desde la interfaz. En Explore se elige Loki para consultar logs.

El dashboard **Laboratorio de Observabilidad - FastAPI** se carga solo, se refresca cada 5 segundos y abre los últimos 15 minutos en la zona horaria del navegador. Representa estos SLIs:

| Panel | SLI | Consulta |
| --- | --- | --- |
| Tasa de solicitudes por segundo | Tráfico de service-a | `sum(rate(app_orders_requests_total{service_name="service-a"}[1m]))` |
| Disponibilidad de pedidos | Porcentaje de solicitudes con `result="success"` | `100 * sum(rate(app_orders_requests_total{service_name="service-a",result="success"}[5m])) / clamp_min(sum(rate(app_orders_requests_total{service_name="service-a"}[5m])), 0.000001)` |
| Porcentaje de errores | Errores de service-a sobre el total | `100 * sum(rate(app_orders_errors_total{service_name="service-a"}[5m])) / clamp_min(sum(rate(app_orders_requests_total{service_name="service-a"}[5m])), 0.000001)` |
| Latencia de pedidos p95 y p99 | Latencia de `app_orders_duration_seconds` | `histogram_quantile(0.95, sum by (le) (rate(app_orders_duration_seconds_bucket{service_name="service-a"}[5m])))` y la misma consulta con `0.99` |
| Uso de CPU por servicio | CPU de service-a y service-b | `100 * sum by (service_name) (process_cpu_utilization_ratio{service_name=~"service-a\|service-b"})` |
| Errores del OpenTelemetry Collector | Datos rechazados o fallidos en el receptor | `sum(rate(otelcol_receiver_refused_spans[5m]))`, `sum(rate(otelcol_receiver_refused_metric_points[5m]))`, `sum(rate(otelcol_receiver_failed_spans[5m]))` y `sum(rate(otelcol_receiver_failed_metric_points[5m]))` |

La disponibilidad usa la etiqueta real `result`. Verde a partir de 99.9, amarillo entre 99 y 99.9, y rojo por debajo de 99. El porcentaje de errores está en verde por debajo de 1, amarillo entre 1 y 5, y rojo por encima de 5.

El Collector de esta versión no publica `otelcol_exporter_send_failed_spans` ni `otelcol_exporter_send_failed_metric_points`. Esas series no están en el panel. Sí existen los contadores de spans y puntos de métrica rechazados o fallidos en el receptor.

Para ver tendencia, genera varias órdenes válidas y al menos una inválida:

```powershell
1..10 | ForEach-Object {
  @'
{"customer_id":"customer-001","amount":150000.50,"currency":"cop"}
'@ | curl.exe -sS -o NUL -w "%{http_code}`n" -X POST http://localhost:8081/api/v1/orders `
    -H "Content-Type: application/json" `
    --data-binary "@-"
}
@'
{"customer_id":"customer-001","amount":150000.50,"currency":"x"}
'@ | curl.exe -sS -o NUL -w "%{http_code}`n" -X POST http://localhost:8081/api/v1/orders `
  -H "Content-Type: application/json" `
  --data-binary "@-"
```

Espera el intervalo de exportación y el scrape. Luego abre el dashboard. Las capturas de referencia van en `evidence/dashboards/01-grafana-complete-dashboard.png`, `evidence/dashboards/02-grafana-latency-panel.png` y `evidence/metrics/02-prometheus-targets-up.png`.

## 11. Logs

service-a y service-b envían logs OTLP gRPC al mismo Collector, con el mismo `Resource` que las trazas y las métricas. El pipeline `logs` usa los procesadores `memory_limiter`, `resource` y `batch`, y el exporter `otlphttp/loki` hacia `http://loki:3100/otlp`. Ese exporter completa solo la ruta `/v1/logs`. Los logs no van a Jaeger ni a Prometheus.

Loki 3.5.12 corre en modo single-binary, con autenticación desactivada, almacenamiento local, esquema TSDB v13, `replication_factor: 1`, `allow_structured_metadata: true` y analítica desactivada. Grafana lo consulta en http://localhost:3000, Explore, data source Loki. El API directo está en http://localhost:3100.

El `LoggingHandler` solo reenvía registros que traen `event.name`, así que el log de acceso de consola no se duplica en Loki. `trace_id` y `span_id` salen del span activo. Una solicitud `WARNING` de Python queda en Loki como `severity_text="WARN"`. Un fallo interno queda como `severity_text="ERROR"`.

En esta versión, Loki convierte el punto del atributo en guion bajo y lo publica como etiqueta:

| Atributo OpenTelemetry | Etiqueta en Loki |
| --- | --- |
| `service.name` | `service_name` |
| `deployment.environment` | `deployment_environment` |
| `event.name` | `event_name` |
| `http.route` | `http_route` |
| `http.request.method` | `http_request_method` |
| `error.type` | `error_type` |
| `trace_id` | `trace_id` |
| `span_id` | `span_id` |

Consultas verificadas:

```logql
{service_name="service-a"}
{service_name="service-b"}
{service_name=~"service-a|service-b"} | severity_text="WARN"
{service_name=~"service-a|service-b"} | severity_text="ERROR"
{service_name=~"service-a|service-b"} | trace_id="4faf809c75ca06fdfcf9170041f67103"
```

Ese `trace_id` es el de una orden válida comprobada en Jaeger y en Loki. Los ocho logs de esa traza comparten el identificador. El `span_id` cambia entre `validate_order`, el span servidor de service-a y `process_order` de service-b.

Para repetir la correlación:

```powershell
@'
{"customer_id":"customer-001","amount":150000.50,"currency":"cop"}
'@ | curl.exe -sS -D - -o NUL -X POST http://localhost:8081/api/v1/orders `
  -H "Content-Type: application/json" --data-binary "@-"
```

Abre http://localhost:16686, busca `service-a` y copia el `trace_id` de `POST /api/v1/orders`. En Grafana Explore, con el data source Loki, ejecuta la consulta de `trace_id`. Deben aparecer logs de service-a y service-b.

Una moneda inválida responde `422` y deja dos logs `WARN`, `order.validation.completed` y `order.request.failed`, con `error_type="VALIDATION_ERROR"`. No incluyen el cuerpo, el cliente, el monto ni credenciales.

```powershell
@'
{"customer_id":"customer-001","amount":150000.50,"currency":"x"}
'@ | curl.exe -sS -w "`n%{http_code}`n" -X POST http://localhost:8081/api/v1/orders `
  -H "Content-Type: application/json" --data-binary "@-"
```

Eventos de service-a: `order.request.received`, `order.validation.completed`, `order.forward.started`, `order.request.completed` y `order.request.failed`.

Eventos de service-b: `order.processing.started`, `order.database.insert.started`, `order.database.insert.completed`, `order.processing.completed` y `order.processing.failed`.

El flujo normal va en `INFO`. Una validación rechazada va en `WARNING`. Un fallo interno, como no poder hablar con service-b o con PostgreSQL, va en `ERROR`. No se registran contraseñas, cadenas de conexión, tokens, cabeceras `Authorization`, datos personales, el cuerpo completo, stack traces ni el entorno completo.

Validación:

```powershell
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs otel-collector --tail 50
docker compose logs loki --tail 50
```

Las capturas están en `evidence/logs/01-loki-service-a-service-b.png`, `evidence/logs/02-log-trace-id-correlation.png`, `evidence/logs/03-error-log.png` y `evidence/traces/03-jaeger-correlated-trace.png`.

## 12. SRE: SLI, SLO, SLA y alertas

La definición completa está en `docs/sre-slo.md`. Las reglas viven en `monitoring/prometheus/rules/slo-rules.yml`.

Los cuatro SLI miden la disponibilidad de pedidos, el porcentaje de solicitudes bajo 500 ms, la tasa de errores y los datos que el Collector rechaza o no procesa. Los SLO internos, en una ventana de 30 días, son 99.9 % de disponibilidad, 95 % de solicitudes bajo 500 ms, menos de 0.1 % de errores y 99.9 % de telemetría sin rechazo. El SLA de ejemplo compromete 99.5 % de disponibilidad mensual: es menos estricto que el SLO para poder corregir antes de una compensación. Esa compensación se revisaría si el mes baja de 99 %.

El presupuesto de error del 99.9 % es 0.1 %: 43 minutos y 12 segundos en 30 días, o como máximo una solicitud fallida de cada mil. Al 50 % se hace una revisión preventiva. Al 75 % se detienen los cambios de alto riesgo. Al 100 % se congelan los despliegues y se prioriza la confiabilidad.

Las alertas, con su runbook, son:

| Alerta | Severidad | Runbook |
| --- | --- | --- |
| `HighOrderErrorRate` | warning | `docs/runbooks/high-error-rate.md` |
| `AvailabilitySLOBreach` | critical | `docs/runbooks/availability-slo-breach.md` |
| `HighOrderP99Latency` | warning | `docs/runbooks/high-latency.md` |
| `OpenTelemetryCollectorExportFailure` | critical | `docs/runbooks/collector-export-failure.md` |

Prometheus las evalúa cada 15 segundos. Las recording rules de ratio usan `clamp_min` y solo publican valor cuando hay tráfico; sin solicitudes la serie queda vacía. El estado se ve en http://localhost:9090/rules y http://localhost:9090/alerts. Grafana tiene el dashboard **SLI, SLO y presupuesto de error**.

Para provocar `HighOrderErrorRate` sin cambiar el umbral, envía durante cerca de dos minutos solicitudes con moneda inválida. Hace falta tráfico y una tasa de errores superior al 5 % durante al menos un minuto.

```powershell
$fin = (Get-Date).AddMinutes(2)
while ((Get-Date) -lt $fin) {
  @'
{"customer_id":"customer-001","amount":150000.50,"currency":"x"}
'@ | curl.exe -sS -o NUL -X POST http://localhost:8081/api/v1/orders `
    -H "Content-Type: application/json" --data-binary "@-"
  Start-Sleep -Milliseconds 400
}
```

Después abre http://localhost:9090/alerts. La misma ráfaga puede activar también `AvailabilitySLOBreach`, porque 5 % de errores ya está por debajo del 99.9 %. `HighOrderP99Latency` no debe dispararse con el laboratorio en local si el p99 sigue bajo 500 ms. `OpenTelemetryCollectorExportFailure` permanece inactive mientras las seis series reales de rechazo y fallo no aumenten. Este Collector no publica métricas de envío fallido del exportador.

## 13. Benchmark: sin OpenTelemetry y con OpenTelemetry

El procedimiento completo está en `docs/benchmark.md`. k6 vive en el profile `benchmark` y no arranca con `docker compose up`. Dentro de la red de Compose, service-a escucha en el puerto **8080**. El puerto `8081` es solo el del host.

`OTEL_SDK_DISABLED=true` no inicializa `TracerProvider`, `MeterProvider` ni `LoggerProvider`, no agrega el handler OTLP y no instrumenta FastAPI, HTTPX ni SQLAlchemy. Los endpoints siguen respondiendo. `false` deja trazas, métricas y logs como hasta ahora.

Antes de cada escenario, con los contenedores healthy y sin otra prueba en marcha:

```powershell
.\load-tests\reset-local-orders.ps1
```

Ese comando solo ejecuta `TRUNCATE TABLE orders` en el PostgreSQL local de este Compose.

Baseline:

```powershell
$env:OTEL_SDK_DISABLED = "true"
docker compose up -d --build --force-recreate --no-deps service-a service-b
docker compose --profile benchmark run --rm --no-deps -e BASE_URL=http://service-a:8080 -e DURATION=30s k6 run /scripts/orders-load-test.js
.\load-tests\collect-docker-stats.ps1 -Scenario baseline
docker compose --profile benchmark run --rm --no-deps -e BASE_URL=http://service-a:8080 -e RESULT_FILE=/results/baseline.json -e K6_WEB_DASHBOARD=true -e K6_WEB_DASHBOARD_EXPORT=/results/baseline-report.html k6 run /scripts/orders-load-test.js
```

El calentamiento de 30 segundos no guarda `RESULT_FILE`. Después, en dos terminales a la vez, lanza la recolección y k6. Cada una dura cinco minutos. En Bash el equivalente es `./load-tests/collect-docker-stats.sh baseline`.

Con OpenTelemetry, el mismo cuerpo, los mismos 50 usuarios, la misma espera de 0,2 s y la misma máquina:

```powershell
$env:OTEL_SDK_DISABLED = "false"
docker compose up -d --force-recreate --no-deps service-a service-b
docker compose --profile benchmark run --rm --no-deps -e BASE_URL=http://service-a:8080 -e DURATION=30s k6 run /scripts/orders-load-test.js
.\load-tests\collect-docker-stats.ps1 -Scenario otel
docker compose --profile benchmark run --rm --no-deps -e BASE_URL=http://service-a:8080 -e RESULT_FILE=/results/otel.json -e K6_WEB_DASHBOARD=true -e K6_WEB_DASHBOARD_EXPORT=/results/otel-report.html k6 run /scripts/orders-load-test.js
```

Análisis:

```powershell
.\.venv\Scripts\python.exe .\load-tests\analyze_results.py
```

Escribe `load-tests/results/comparison.md` y `load-tests/results/comparison.csv`. CPU y memoria salen de `docker stats`, no del SDK, porque el baseline no exporta esas métricas.

Resultado de esta máquina, el 8 de octubre de 2026:

| Métrica | Baseline | OpenTelemetry | Overhead |
| --- | ---: | ---: | ---: |
| Latencia promedio | 256,72 ms | 321,60 ms | 25,27 % |
| Latencia p95 | 448,27 ms | 619,27 ms | 38,15 % |
| Latencia p99 | 538,52 ms | 822,78 ms | 52,78 % |
| Solicitudes por segundo | 109,21 | 95,66 | 12,41 % de degradación |
| Errores | 0 % | 0 % | no calculable, el baseline es cero |
| CPU promedio service-a | 57,21 % | 71,00 % | 24,12 % |
| CPU promedio service-b | 91,95 % | 98,27 % | 6,88 % |
| Memoria promedio service-a | 61,77 MiB | 68,92 MiB | 11,58 % |
| Memoria promedio service-b | 98,85 MiB | 87,00 MiB | -11,99 % |

Los dos escenarios usaron 50 usuarios durante 300 s. Los errores cumplieron el umbral del 1 %. El p99 no cumplió 500 ms ni siquiera en el baseline. La diferencia es visible, pero el portátil también mete ruido: no se concluye que OpenTelemetry sea la única causa. La memoria de service-b bajó en la segunda pasada. Al terminar, deja `OTEL_SDK_DISABLED=false`.

Limitaciones: una sola corrida local, sin aislar CPU, con el calentamiento fuera del resultado y con `docker stats` cada unos cinco segundos. No representa producción. Muestrear trazas, subir el intervalo de métricas o ampliar los lotes bajaría el costo a cambio de menos detalle.

## 14. Integración continua

El workflow está en la raíz del repositorio Git, en `.github/workflows/ci.yml`, porque el laboratorio vive en la carpeta `otel-multicloud-lab` y GitHub Actions no ejecuta workflows anidados. Se dispara en cada `push`, en cada `pull_request` y también se puede lanzar a mano. Comprueba que los dos servicios pasan sus pruebas, que sus imágenes Docker se construyen y que Terraform tiene formato y sintaxis válidos. No inicia sesión en AWS ni en GCP, no ejecuta `plan`, `apply` ni `destroy`, no publica imágenes y no crea recursos.

En orden hace esto:

1. Instala las dependencias de service-a y ejecuta Pytest.
2. Instala las dependencias de service-b y ejecuta Pytest.
3. Construye las dos imágenes con `docker build` y las deja solo en el runner.
4. Ejecuta `terraform fmt -check -recursive`.
5. Ejecuta `terraform init -backend=false` y `terraform validate` en `infrastructure/aws` y en `infrastructure/gcp`.

Esas raíces de Terraform no contienen recursos ni proveedores. El pipeline usa Terraform 1.16.5 y las acciones fijadas por el commit `actions/checkout` v7.0.1, `actions/setup-python` v7.0.0 y `hashicorp/setup-terraform` v4.0.1.

## 15. Detener los contenedores

```powershell
docker compose stop
```

Los contenedores, el volumen y la red se conservan. Para volver a arrancar sin reconstruir:

```powershell
docker compose start
```

## 16. Limpiar solo los recursos de este proyecto

Este comando elimina los contenedores, la red `otel-multicloud-lab`, los volúmenes `otel-multicloud-lab-postgres` y `otel-multicloud-lab-loki`, y las imágenes construidas por los Dockerfiles de este Compose. No borra contenedores, volúmenes ni redes de otros proyectos.

```powershell
docker compose down --volumes --remove-orphans --rmi local
```

La imagen pública `postgres:16-alpine` permanece en la caché local de Docker porque Compose la descarga y no la construye. Quítala aparte solo si quieres liberar ese espacio:

```powershell
docker image rm postgres:16-alpine
```
