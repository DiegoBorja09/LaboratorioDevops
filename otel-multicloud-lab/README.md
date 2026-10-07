# otel-multicloud-lab

Laboratorio académico de observabilidad. Esta primera fase entrega dos microservicios funcionales y una base PostgreSQL. OpenTelemetry no está instalado: la aplicación sirve como línea base para instrumentarla después y comparar el rendimiento con y sin observabilidad.

## 1. Requisitos

- Docker y Docker Compose v2
- Python 3.12, solo si vas a ejecutar las pruebas fuera de Docker
- curl

No hace falta clonar otros repositorios ni configurar un recopilador. Las carpetas `collector/`, `monitoring/`, `infrastructure/`, `load-tests/`, `evidence/` y `docs/` quedan reservadas para fases posteriores.

## 2. Arquitectura y flujo de la solicitud

```text
Cliente → service-a → HTTP → service-b → PostgreSQL
```

1. El cliente llama a `POST /api/v1/orders` en service-a (puerto local 8081).
2. service-a valida el cuerpo con Pydantic, ejecuta `validate_order` y reenvía la orden con HTTPX, en un solo intento, a `POST /api/v1/orders/process`.
3. service-b ejecuta `process_order`, guarda la fila en la tabla `orders` y responde `201`.
4. service-a devuelve al cliente el resultado de service-b.

El header `X-Request-ID` viaja en la petición y en la respuesta. Si el cliente no lo envía, service-a genera un UUID. Los logs de ambos servicios son JSON e incluyen `request_id`, método, ruta, código de estado y duración cuando esos datos existen. Todavía no hay `trace_id` ni `span_id`.

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

## 8. Detener los contenedores

```powershell
docker compose stop
```

Los contenedores, el volumen y la red se conservan. Para volver a arrancar sin reconstruir:

```powershell
docker compose start
```

## 9. Limpiar solo los recursos de este proyecto

Este comando elimina los contenedores, la red `otel-multicloud-lab`, el volumen `otel-multicloud-lab-postgres` y las imágenes construidas por los Dockerfiles de este Compose. No borra contenedores, volúmenes ni redes de otros proyectos.

```powershell
docker compose down --volumes --remove-orphans --rmi local
```

La imagen pública `postgres:16-alpine` permanece en la caché local de Docker porque Compose la descarga y no la construye. Quítala aparte solo si quieres liberar ese espacio:

```powershell
docker image rm postgres:16-alpine
```
