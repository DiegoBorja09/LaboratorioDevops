# otel-multicloud-lab

Laboratorio académico de observabilidad. La aplicación base sigue igual: service-a, service-b y PostgreSQL. service-a y service-b exportan trazas distribuidas por OTLP hacia un OpenTelemetry Collector y Jaeger. Las métricas y la exportación de logs por OTLP todavía no están implementadas.

## 1. Requisitos

- Docker y Docker Compose v2
- Python 3.12, solo si vas a ejecutar las pruebas fuera de Docker
- curl

El Collector local vive en `collector/`. Las carpetas `monitoring/`, `infrastructure/`, `load-tests/`, `evidence/` y `docs/` quedan reservadas para fases posteriores.

## 2. Arquitectura y flujo de la solicitud

```text
Cliente → service-a → HTTP → service-b → PostgreSQL
```

1. El cliente llama a `POST /api/v1/orders` en service-a (puerto local 8081).
2. service-a valida el cuerpo con Pydantic, ejecuta `validate_order` y reenvía la orden con HTTPX, en un solo intento, a `POST /api/v1/orders/process`.
3. service-b ejecuta `process_order`, guarda la fila en la tabla `orders` y responde `201`.
4. service-a devuelve al cliente el resultado de service-b.

El header `X-Request-ID` viaja en la petición y en la respuesta. Si el cliente no lo envía, service-a genera un UUID. Los logs de ambos servicios siguen siendo JSON e incluyen `request_id`, método, ruta, código de estado y duración cuando esos datos existen. Los logs todavía no llevan `trace_id` ni `span_id`: la correlación de la traza está en Jaeger.

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
| `OTEL_RESOURCE_ATTRIBUTES` | Atributos del recurso | service-a: `service.version=1.0.0,deployment.environment=local`. service-b añade `service.namespace=otel-multicloud-lab` |
| `OTEL_SDK_DISABLED` | Desactiva el SDK en las pruebas | `true` solo en Pytest |

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
```

Jerarquía esperada de `POST /api/v1/orders`:

1. `POST /api/v1/orders`, service-a, servidor.
2. `validate_order`, service-a.
3. Llamada HTTPX a service-b, service-a, cliente.
4. `POST /api/v1/orders/process`, service-b, servidor.
5. `process_order`, service-b.
6. `INSERT` de SQLAlchemy hacia PostgreSQL, service-b.

SQLAlchemy puede añadir spans de conexión, transacción o commit. No debe haber dos spans idénticos para la misma consulta. Los spans no incluyen `customer_id`, el monto, el cuerpo de la petición ni la contraseña de la base.

Si el Collector no está disponible, los dos servicios arrancan y procesan órdenes igual. Las métricas y la exportación de logs por OTLP todavía no están implementadas.

Para ver una traza:

```powershell
docker compose up -d --build
docker compose ps
docker compose logs service-b --tail=100
docker compose logs otel-collector --tail=100
```

Crea una orden con el `POST` de la sección anterior y abre http://localhost:16686. En Jaeger elige el servicio `service-a`, pulsa Find Traces y abre la traza del `POST /api/v1/orders`. En el detalle deben aparecer service-a y service-b, los spans HTTP, `process_order` y el span de PostgreSQL. Una captura de referencia está en `evidence/traces/02-distributed-trace-service-a-service-b-db.png`.

## 9. Detener los contenedores

```powershell
docker compose stop
```

Los contenedores, el volumen y la red se conservan. Para volver a arrancar sin reconstruir:

```powershell
docker compose start
```

## 10. Limpiar solo los recursos de este proyecto

Este comando elimina los contenedores, la red `otel-multicloud-lab`, el volumen `otel-multicloud-lab-postgres` y las imágenes construidas por los Dockerfiles de este Compose. No borra contenedores, volúmenes ni redes de otros proyectos.

```powershell
docker compose down --volumes --remove-orphans --rmi local
```

La imagen pública `postgres:16-alpine` permanece en la caché local de Docker porque Compose la descarga y no la construye. Quítala aparte solo si quieres liberar ese espacio:

```powershell
docker image rm postgres:16-alpine
```
