# SLI, SLO, SLA y presupuesto de error

Estos objetivos son académicos. Sirven para ejercitar el ciclo de confiabilidad del laboratorio. En un negocio real hay que recalcularlos con el tráfico, el impacto de un fallo y lo que el contrato pueda sostener.

## Qué significa cada término

| Concepto | Qué responde | En este laboratorio |
| --- | --- | --- |
| SLI | Qué se mide | Ratios y contadores calculados con Prometheus |
| SLO | Qué meta interna se persigue | Más estricto que el compromiso externo |
| SLA | Qué se promete por contrato | Menos estricto que el SLO, para tener margen antes de compensar |

El SLA de ejemplo (99.5 %) es menos estricto que el SLO interno de disponibilidad (99.9 %). Así el equipo puede detectar el desvío y corregirlo antes de incumplir el contrato.

## SLI 1 — Disponibilidad

Porcentaje de solicitudes de pedidos que terminan correctamente.

```text
solicitudes exitosas / solicitudes totales
```

Métricas reales de service-a:

- `app_orders_requests_total`, con `result="success"` para las exitosas y sin ese filtro para el total
- `app_orders_errors_total` para contrastar los fallos

PromQL de la ventana de 5 minutos:

```promql
sum(rate(app_orders_requests_total{service_name="service-a",result="success"}[5m]))
/
clamp_min(sum(rate(app_orders_requests_total{service_name="service-a"}[5m])), 0.000001)
```

`clamp_min` evita dividir por cero. La recording rule solo publica el ratio cuando la tasa de solicitudes es mayor que cero; sin tráfico la serie queda vacía y no se interpreta como 0 % de disponibilidad. La alerta usa la misma condición.

## SLI 2 — Latencia

Porcentaje de solicitudes de pedidos completadas en menos de 500 ms.

El histograma real es `app_orders_duration_seconds_bucket`. El cubo `le="0.5"` existe en esta instrumentación y agrupa las observaciones de hasta medio segundo.

```promql
sum(rate(app_orders_duration_seconds_bucket{service_name="service-a",le="0.5"}[5m]))
/
clamp_min(sum(rate(app_orders_duration_seconds_count{service_name="service-a"}[5m])), 0.000001)
```

p95 y p99 salen del mismo histograma con `histogram_quantile`. La recording rule del porcentaje bajo 500 ms solo emite valor cuando hay observaciones en la ventana.

## SLI 3 — Tasa de errores

Porcentaje de solicitudes que terminan con error.

```text
errores / solicitudes totales
```

```promql
sum(rate(app_orders_errors_total{service_name="service-a"}[5m]))
/
clamp_min(sum(rate(app_orders_requests_total{service_name="service-a"}[5m])), 0.000001)
```

`app_orders_errors_total` cuenta las respuestas de service-a que no son exitosas, incluidas las validaciones `422` y los fallos al llamar a service-b.

## SLI 4 — Salud de la telemetría

Cantidad de spans, logs o puntos de métrica que el OpenTelemetry Collector rechaza o no consigue procesar.

Series reales en este Collector 0.162:

- `otelcol_receiver_refused_spans`
- `otelcol_receiver_refused_log_records`
- `otelcol_receiver_refused_metric_points`
- `otelcol_receiver_failed_spans`
- `otelcol_receiver_failed_log_records`
- `otelcol_receiver_failed_metric_points`

No existen `otelcol_exporter_send_failed_spans`, `otelcol_exporter_send_failed_metric_points` ni `otelcol_exporter_send_failed_log_records`. La alerta no las inventa. Usa el incremento de las seis series anteriores.

## SLO

| SLO | Objetivo interno | Ventana |
| --- | --- | --- |
| Disponibilidad | 99.9 % de solicitudes exitosas | 30 días |
| Latencia | Al menos 95 % de las solicitudes terminan en menos de 500 ms | 30 días |
| Errores | La tasa de errores se mantiene por debajo de 0.1 % | 30 días |
| Telemetría | 99.9 % de los datos de observabilidad se procesan sin rechazo. No hay fallos continuos de recepción o exportación durante más de cinco minutos | 30 días |

El 0.1 % de errores es el complemento del 99.9 % de disponibilidad cuando éxito y error parten el total. La latencia es un objetivo distinto: una solicitud puede ser exitosa y, aun así, pasar de 500 ms.

## SLA de ejemplo

Compromiso externo, no la meta con la que opera el equipo:

- Disponibilidad mensual comprometida: 99.5 %.
- Si la disponibilidad baja de 99.5 %, se inicia la revisión del incidente.
- Si baja de 99 %, se aplicaría una compensación de servicio definida en el contrato.

99.5 % permite más indisponibilidad que 99.9 %. El margen entre el SLO y el SLA es el tiempo del que dispone el equipo para recuperar el servicio antes de deber una compensación.

## Presupuesto de error

El SLO de disponibilidad del 99.9 % en 30 días deja un presupuesto del 0.1 %.

```text
30 días × 24 h × 60 min × 0.001 = 43.2 minutos = 43 minutos y 12 segundos
```

En un modelo basado en solicitudes, el mismo 0.1 % es el máximo de solicitudes fallidas sobre el total del mes. Mil solicitudes permiten una fallida. Un millón permiten mil.

| Objetivo | Ventana | Error budget | Al 50 % | Al 75 % | Al 100 % |
| --- | --- | --- | --- | --- | --- |
| Disponibilidad 99.9 % | 30 días | 0.1 %, unos 43 min 12 s, o 0.1 % de las solicitudes | Revisión preventiva | Detener cambios de alto riesgo | Congelar despliegues y priorizar confiabilidad |
| Latencia: 95 % bajo 500 ms | 30 días | 5 % de solicitudes por encima de 500 ms | Revisión preventiva | Detener cambios de alto riesgo | Congelar despliegues y priorizar confiabilidad |
| Errores bajo 0.1 % | 30 días | 0.1 % de solicitudes fallidas | Revisión preventiva | Detener cambios de alto riesgo | Congelar despliegues y priorizar confiabilidad |
| Telemetría 99.9 % sin rechazo | 30 días | 0.1 % de datos rechazados o fallidos, sin un fallo continuo de más de 5 min | Revisión preventiva | Detener cambios de alto riesgo | Congelar despliegues y priorizar confiabilidad |

Las reglas de Prometheus en `monitoring/prometheus/rules/slo-rules.yml` observan ventanas de 5 minutos. Sirven para reaccionar pronto. No sustituyen el cálculo mensual del presupuesto: una ráfaga de pruebas puede consumir la ventana corta sin haber agotado los 43 minutos del mes.
