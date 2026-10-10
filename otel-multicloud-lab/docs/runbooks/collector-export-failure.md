# Fallo de recepción o exportación en el OpenTelemetry Collector

Alerta: `OpenTelemetryCollectorExportFailure`

Runbook: `docs/runbooks/collector-export-failure.md`

## Descripción

Durante al menos un minuto aumentaron spans, logs o puntos de métrica rechazados o fallidos en el receptor del Collector.

Series usadas, que sí existen en esta versión:

- `otelcol_receiver_refused_spans`
- `otelcol_receiver_refused_log_records`
- `otelcol_receiver_refused_metric_points`
- `otelcol_receiver_failed_spans`
- `otelcol_receiver_failed_log_records`
- `otelcol_receiver_failed_metric_points`

No existen `otelcol_exporter_send_failed_spans`, `otelcol_exporter_send_failed_metric_points` ni `otelcol_exporter_send_failed_log_records`. El SLO de telemetría pide procesar el 99.9 % de los datos sin rechazo y no sostener un fallo continuo por más de cinco minutos.

## Impacto

Jaeger, Prometheus o Loki dejan de ver parte de la señal. La API de pedidos puede seguir respondiendo: un fallo del Collector no debe tumbar service-a ni service-b.

## Posibles causas

- Loki, Jaeger o el propio Collector reiniciados o sin memoria.
- El límite del `memory_limiter` rechaza datos.
- El pipeline de logs no llega a `http://loki:3100/otlp`.
- Demasiada cardinalidad o un exportador caído.

## Validaciones iniciales

```powershell
docker compose ps otel-collector loki jaeger prometheus
docker compose logs otel-collector --tail 100
curl.exe -sS http://localhost:13133
curl.exe -sS http://localhost:3100/ready
```

En http://localhost:9090/targets, los jobs `otel-collector` y `otel-collector-internal` deben estar UP.

## Consultas PromQL

```promql
sum(increase(otelcol_receiver_refused_spans[5m]))
sum(increase(otelcol_receiver_refused_log_records[5m]))
sum(increase(otelcol_receiver_refused_metric_points[5m]))
sum(increase(otelcol_receiver_failed_spans[5m]))
sum(increase(otelcol_receiver_failed_log_records[5m]))
sum(increase(otelcol_receiver_failed_metric_points[5m]))
sum(rate(otelcol_exporter_sent_spans[5m]))
sum(rate(otelcol_exporter_sent_log_records[5m]))
sum(rate(otelcol_exporter_sent_metric_points[5m]))
up{job=~"otel-collector|otel-collector-internal"}
```

`otelcol_exporter_sent_*` confirma que el envío sigue. No sustituye a una serie de fallos de envío que este Collector no publica.

## Consultas LogQL

```logql
{service_name=~"service-a|service-b"}
```

Si Loki no devuelve logs nuevos mientras los servicios responden, el pipeline de logs está roto aunque la API esté sana.

## Traza en Jaeger

Genera un `POST` válido a http://localhost:8081/api/v1/orders y ábrelo en http://localhost:16686. Si no aparece, el pipeline de trazas no está entregando a Jaeger. Anota la hora y compárala con el incremento de `otelcol_receiver_refused_spans` o `otelcol_receiver_failed_spans`.

## Mitigación

- Reinicia solo el componente caído: `docker compose restart loki` o `docker compose restart jaeger`. Después reinicia el Collector si hacía falta volver a resolver el nombre.
- Si el log del Collector muestra el memory limiter, baja la carga de prueba antes de subir el límite.
- Confirma que los tres pipelines siguen definidos: `traces`, `metrics` y `logs`.
- No envíes logs a Jaeger ni métricas al exporter de Prometheus de aplicación.

## Evidencias

- Estado de la alerta en http://localhost:9090/alerts.
- Targets UP o DOWN.
- Fragmento del log del Collector sin secretos.
- Una traza posterior a la mitigación, con su `trace_id`.

## Cierre

Durante cinco minutos seguidos el incremento de las seis series de rechazo y fallo vuelve a cero, los targets están UP, un pedido nuevo tiene traza en Jaeger y sus logs aparecen en Loki con el mismo `trace_id`.
