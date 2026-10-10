# Latencia p99 de pedidos por encima de 500 ms

Alerta: `HighOrderP99Latency`

Runbook: `docs/runbooks/high-latency.md`

## Descripción

El percentil 99 de `app_orders_duration_seconds` de service-a superó 0.5 segundos durante al menos dos minutos. El SLO pide que al menos el 95 % de las solicitudes terminen en menos de 500 ms.

## Impacto

La API sigue respondiendo, pero la experiencia se degrada. Un p99 alto puede convivir con una disponibilidad del 100 %: el SLO de latencia es independiente del de errores.

## Posibles causas

- service-b o PostgreSQL lentos.
- Timeout cercano a los 5 segundos de la llamada HTTP de service-a.
- Contención de CPU del contenedor. La métrica de proceso es `process_cpu_utilization_ratio`.
- Pocas muestras en la ventana: `histogram_quantile` se vuelve inestable si casi no hay tráfico.

## Validaciones iniciales

```powershell
docker compose ps
docker compose stats --no-stream service-a service-b postgres
```

## Consultas PromQL

```promql
sre:orders:latency_p99_seconds_5m
sre:orders:latency_p95_seconds_5m
sre:orders:latency_under_500ms_ratio_5m
histogram_quantile(0.99, sum by (le) (rate(app_orders_duration_seconds_bucket{service_name="service-a"}[5m])))
histogram_quantile(0.99, sum by (le) (rate(app_orders_processing_duration_seconds_bucket{service_name="service-b"}[5m])))
100 * sum by (service_name) (process_cpu_utilization_ratio{service_name=~"service-a|service-b"})
```

## Consultas LogQL

```logql
{service_name="service-a"} | event_name="order.forward.started"
{service_name="service-b"} | event_name="order.database.insert.completed"
{service_name=~"service-a|service-b"} | severity_text="ERROR"
```

Compara la hora del reenvío con la de la inserción. El log no incluye el cuerpo ni el SQL.

## Traza en Jaeger

Abre http://localhost:16686 y ordena por duración. En la traza de `POST /api/v1/orders` mira qué span aporta más tiempo: `validate_order`, el cliente HTTP, `process_order` o `INSERT`. El `trace_id` debe ser el mismo que en Loki.

## Mitigación

- Si el span lento es `INSERT` o `connect`, revisa PostgreSQL y el pool. No instrumentes asyncpg aparte.
- Si el span lento es el cliente HTTP, revisa service-b antes de subir el timeout.
- Si la CPU del contenedor está saturada, reduce carga de prueba.
- No cambies el umbral de 500 ms para silenciar la alerta.

## Evidencias

- Gráfica de p95 y p99.
- Valor de `sre:orders:latency_under_500ms_ratio_5m`.
- Traza de Jaeger del pedido lento, con el `trace_id` visible.

## Cierre

`sre:orders:latency_p99_seconds_5m` se mantiene en 0.5 segundos o menos durante al menos diez minutos con tráfico, y al menos el 95 % de las muestras de la ventana caen en el cubo de 500 ms.
