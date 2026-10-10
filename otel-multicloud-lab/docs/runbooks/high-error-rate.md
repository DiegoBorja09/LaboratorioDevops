# Alta tasa de errores de pedidos

Alerta: `HighOrderErrorRate`

Runbook: `docs/runbooks/high-error-rate.md`

## Descripción

Más del 5 % de las solicitudes de `POST /api/v1/orders` en service-a terminaron en error durante al menos un minuto, y había tráfico.

## Impacto

Los clientes reciben `422`, `502` o `504` en lugar de `201`. La disponibilidad se acerca al límite del SLO de 99.9 % y el presupuesto de error de la ventana corta se consume rápido.

## Posibles causas

- Cuerpos inválidos: moneda distinta de tres caracteres, monto no positivo o JSON mal formado.
- service-b no acepta la conexión o responde `5xx`.
- PostgreSQL no está sano y service-b no puede insertar.
- El timeout de service-a, 5 segundos, se agota.

## Validaciones iniciales

```powershell
docker compose ps
curl.exe -sS http://localhost:8081/health
curl.exe -sS http://localhost:8082/health
```

## Consultas PromQL

```promql
sre:orders:error_ratio_5m
sre:orders:request_rate_5m
sre:orders:availability_ratio_5m
sum by (http_response_status_code, result) (rate(app_orders_requests_total{service_name="service-a"}[5m]))
sum by (http_response_status_code) (rate(app_orders_errors_total{service_name="service-a"}[5m]))
sum(rate(app_orders_processing_errors_total{service_name="service-b"}[5m]))
```

## Consultas LogQL

```logql
{service_name="service-a"} | event_name="order.request.failed"
{service_name="service-a"} | severity_text="WARN"
{service_name="service-a"} | severity_text="ERROR"
{service_name="service-b"} | event_name="order.processing.failed"
```

Revisa `error_type`, `http_response` no está en el log: el resultado está en `result` y `error_type`. No busques el cuerpo ni el monto.

## Traza en Jaeger

1. Copia el `trace_id` de un log `order.request.failed` en Grafana Explore.
2. Abre http://localhost:16686.
3. Busca el servicio `service-a` o pega el `trace_id`.
4. Confirma si la traza se detiene en `validate_order` o si llega a service-b y a `INSERT`.

## Mitigación

- Si `error_type` es `VALIDATION_ERROR`, el fallo es de contrato del cliente. No reinicies los servicios. Corrige el cuerpo de prueba: `currency` de tres letras y `amount` positivo.
- Si es `SERVICE_B_UNAVAILABLE` o `SERVICE_B_TIMEOUT`, revisa `docker compose logs service-b --tail 100` y el health de service-b.
- Si service-b registra `order.processing.failed`, revisa PostgreSQL con `docker compose ps` y `docker compose logs postgres --tail 50`.
- No bajes el umbral del 5 % para que la alerta desaparezca.

## Evidencias

- Captura de http://localhost:9090/alerts con `HighOrderErrorRate`.
- Consulta PromQL de `sre:orders:error_ratio_5m`.
- Log de Loki y traza de Jaeger del mismo `trace_id`, si el error ocurrió dentro de un span.

## Cierre

La alerta pasa a inactive, `sre:orders:error_ratio_5m` se mantiene por debajo de 0.05 con tráfico real durante al menos diez minutos y quedó registrada la causa. Si el presupuesto mensual llega al 100 %, se congelan los despliegues hasta recuperar confiabilidad.
