# Benchmark local: sin OpenTelemetry y con OpenTelemetry

La prueba compara el mismo `POST /api/v1/orders` con el SDK apagado y encendido. No sustituye las métricas de la aplicación: CPU y memoria salen de `docker stats`.

Dentro de Docker, service-a escucha en el puerto **8080**. El `8081` del host no existe en la red de Compose. k6 usa `http://service-a:8080`.

La base genera `id` y `request_id`. El cuerpo puede repetirse sin identificadores nuevos:

```json
{"customer_id":"bench-customer","amount":150000.50,"currency":"cop"}
```

`bench-customer` es un identificador de laboratorio, no un dato personal.

## Antes de cada escenario

- Cierra aplicaciones que no hagan falta y no lances otra prueba a la vez.
- Espera a que `service-a` y `service-b` estén healthy.
- Vacía solo la tabla local `orders`.
- Haz un calentamiento de 30 segundos. Ese resultado no se guarda.
- Usa los mismos 50 usuarios, 5 minutos, endpoint y 0,2 s de espera.

```powershell
.\load-tests\reset-local-orders.ps1
```

Ese script ejecuta `TRUNCATE TABLE orders` únicamente en el PostgreSQL de este Compose. No toca otras bases.

## Baseline

Desde la raíz del repositorio:

```powershell
$env:OTEL_SDK_DISABLED = "true"
docker compose up -d --build --force-recreate --no-deps service-a service-b
docker compose ps
```

Comprueba que un pedido válido responde 201 y que Jaeger, Loki y Prometheus no reciben señales nuevas de esa petición. El procedimiento automatizado de esta entrega hace esa comprobación antes de medir.

Calentamiento, fuera de los resultados:

```powershell
docker compose --profile benchmark run --rm --no-deps `
  -e BASE_URL=http://service-a:8080 `
  -e DURATION=30s `
  k6 run /scripts/orders-load-test.js
```

Medición de cinco minutos. Arranca los dos comandos a la vez:

```powershell
.\load-tests\collect-docker-stats.ps1 -Scenario baseline
```

```powershell
docker compose --profile benchmark run --rm --no-deps `
  -e BASE_URL=http://service-a:8080 `
  -e RESULT_FILE=/results/baseline.json `
  -e K6_WEB_DASHBOARD=true `
  -e K6_WEB_DASHBOARD_EXPORT=/results/baseline-report.html `
  k6 run /scripts/orders-load-test.js
```

Quedan `load-tests/results/baseline.json` y `load-tests/results/baseline-resources.csv`.

## Con OpenTelemetry

```powershell
$env:OTEL_SDK_DISABLED = "false"
docker compose up -d --force-recreate --no-deps service-a service-b
docker compose ps
```

Comprueba que vuelven trazas, métricas de `app_orders_requests_total` y logs con `service_name`. Repite el vaciado de `orders` y el mismo calentamiento de 30 segundos.

```powershell
.\load-tests\collect-docker-stats.ps1 -Scenario otel
```

```powershell
docker compose --profile benchmark run --rm --no-deps `
  -e BASE_URL=http://service-a:8080 `
  -e RESULT_FILE=/results/otel.json `
  -e K6_WEB_DASHBOARD=true `
  -e K6_WEB_DASHBOARD_EXPORT=/results/otel-report.html `
  k6 run /scripts/orders-load-test.js
```

Quedan `load-tests/results/otel.json` y `load-tests/results/otel-resources.csv`.

Al terminar, deja `OTEL_SDK_DISABLED=false` para que Jaeger, Prometheus y Loki sigan recibiendo la telemetría del laboratorio.

## Recursos en Bash

```bash
./load-tests/collect-docker-stats.sh baseline
./load-tests/collect-docker-stats.sh otel
```

## Análisis

```powershell
.\.venv\Scripts\python.exe .\load-tests\analyze_results.py
```

Genera `load-tests/results/comparison.md` y `load-tests/results/comparison.csv`. Si falta un archivo o una métrica, el análisis se detiene o escribe `ausente`. No rellena huecos.
