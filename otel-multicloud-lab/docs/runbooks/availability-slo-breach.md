# Incumplimiento del SLO de disponibilidad

Alerta: `AvailabilitySLOBreach`

Runbook: `docs/runbooks/availability-slo-breach.md`

## Descripción

La disponibilidad de pedidos de service-a estuvo por debajo del 99.9 % durante al menos dos minutos, con tráfico presente. El SLO interno es más estricto que el SLA de ejemplo del 99.5 %.

## Impacto

Parte de las solicitudes no terminan en éxito. Si el desvío se mantiene el mes, se consume el presupuesto de 43 minutos y 12 segundos. Por debajo del 99.5 % mensual empezaría la revisión contractual. Por debajo del 99 % aplicaría la compensación definida en el contrato.

## Posibles causas

- La misma causa que eleva la tasa de errores: validación, service-b o PostgreSQL.
- Un despliegue reciente que cambió el contrato o la conexión entre servicios.
- Tráfico de prueba con muchos cuerpos inválidos. En el laboratorio eso consume el SLO de la ventana corta aunque no represente el mes completo.

## Validaciones iniciales

```powershell
docker compose ps
curl.exe -sS http://localhost:8081/health
curl.exe -sS http://localhost:8082/health
```

## Consultas PromQL

```promql
sre:orders:availability_ratio_5m
sre:orders:error_ratio_5m
sre:orders:request_rate_5m
sum(rate(app_orders_requests_total{service_name="service-a",result="success"}[5m]))
sum(rate(app_orders_requests_total{service_name="service-a"}[5m]))
```

El presupuesto consumido en la ventana de 5 minutos, respecto del 0.1 % permitido, es:

```promql
clamp_max(100 * sre:orders:error_ratio_5m / 0.001, 100)
```

Esa cifra no es el consumo de los 30 días.

## Consultas LogQL

```logql
{service_name="service-a"} | result="error"
{service_name=~"service-a|service-b"} | severity_text=~"WARN|ERROR"
```

## Traza en Jaeger

Abre http://localhost:16686, elige `service-a` y compara una traza exitosa con una fallida. El `trace_id` del log en Loki debe coincidir con el de Jaeger. En un éxito aparecen `validate_order`, la llamada HTTP, `process_order` e `INSERT`. En una validación rechazada la traza no tiene que llegar a PostgreSQL.

## Mitigación

- Al 50 % del presupuesto de la ventana: revisión preventiva de los errores por `error_type`.
- Al 75 %: no introduzcas cambios de alto riesgo en el flujo de pedidos.
- Al 100 %: congela despliegues y prioriza la confiabilidad.
- Separa el tráfico de prueba inválido del tráfico que quieres usar como medida del mes.
- Restaura service-b y PostgreSQL si el health no responde.

## Evidencias

- Valor de `sre:orders:availability_ratio_5m`.
- Panel de disponibilidad del dashboard SRE.
- Una traza fallida y, si existe, una exitosa del mismo intervalo.

## Cierre

La alerta queda inactive, la disponibilidad de la ventana vuelve a 99.9 % o más con tráfico legítimo y la causa quedó anotada. El SLA de 99.5 % solo se considera incumplido si el agregado mensual baja de ese valor, no por una ráfaga de cinco minutos.
