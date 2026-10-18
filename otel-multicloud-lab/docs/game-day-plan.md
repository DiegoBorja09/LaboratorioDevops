# Game Day del laboratorio de observabilidad

Informe técnico del ejercicio ejecutado el 2026-10-18 en `otel-multicloud-lab`. El único fallo inyectado fue latencia de salida en service-b. No se repitió el caos para escribir este documento y no se desplegó infraestructura en AWS ni en GCP. Los experimentos de CPU y de partición están diseñados y no tienen resultados.

## 1. Objetivo

Comprobar, con el flujo real de creación de órdenes, qué ocurre cuando service-b sufre un retraso de red acotado, y dejar preparados otros dos fallos. La pregunta del fallo ejecutado es si 200 ms añadidos en service-b durante 120 s se observan como unos 200 ms más de latencia, sin perder disponibilidad ni elevar la tasa de errores, y si el sistema vuelve a la línea base como máximo 30 s después de retirar el fallo.

## 2. Arquitectura

El ejercicio usa Docker Compose en local. k6 llama a service-a; service-a llama a service-b; service-b escribe en PostgreSQL. Collector, Jaeger, Prometheus, Loki y Grafana observan ese camino.

| Pieza | Papel en el Game Day |
| --- | --- |
| service-a, host 8081, contenedor 8080 | Recibe `POST /api/v1/orders` y espera a service-b |
| service-b, host 8082, contenedor 8080 | Procesa la orden e inserta la fila |
| PostgreSQL, host 5433, contenedor 5432 | Base `orders_db` |
| k6 2.3.0 en la red `otel-multicloud-lab` | 5 usuarios virtuales contra `http://service-a:8080` |
| Jaeger, Prometheus, Loki, Grafana, Collector | Evidencia de trazas, métricas y logs |

La orden aceptada responde 201. El cuerpo de la carga es `customer_id` `bench-customer`, `amount` 150000.5 y `currency` `cop`. Cada iteración envía su propio `X-Request-ID`.

En el código, service-a espera esa llamada con un timeout de 5 s. Si vence, responde 504 `SERVICE_B_TIMEOUT`. Si service-b responde 5xx o no se puede conectar, responde 502. service-b confirma la orden con `commit` y luego `refresh`. El engine de base solo activa `pool_pre_ping`; no declara tamaño de pool ni timeout de comando. No hay circuit breaker, reintentos ni límite de concurrencia en ese camino.

service-b se ejecutó con la imagen de caos, que añade `iproute2`, y con `NET_ADMIN`. La API siguió bajo el usuario `app`. `tc` se lanzó como root dentro del contenedor. No se usó el modo privilegiado.

## 3. Estado estable

Están en ejecución service-a, service-b, postgres, grafana, prometheus, jaeger, loki y otel-collector. service-a responde `healthy`. service-b responde `healthy` y `database` = `connected`.

La línea base, 120 s y 5 usuarios, midió un p95 de 18.302411 ms, cero fallos HTTP y el 100 % de checks, a 23.218029 peticiones/s.

## 4. Hipótesis

Hipótesis 1, latencia: "En estado estable, cuando se agregan 200 ms de latencia a service-b durante 120 segundos, esperamos que service-a mantenga una disponibilidad mínima del 99 %, una tasa de errores inferior al 1 %, que la latencia p95 aumente aproximadamente 200 ms y que regrese al rango normal máximo 30 segundos después del rollback."

Hipótesis 2, CPU: "En estado estable, cuando service-b sostiene un consumo de CPU del 90 % durante 120 segundos, esperamos que la disponibilidad de service-a se mantenga en al menos el 99 %, que la tasa de errores permanezca bajo el 1 % y que el p95 de `POST /api/v1/orders` suba durante la presión y vuelva al rango de la línea base al terminar el proceso que consume la CPU."

Hipótesis 3, partición: "En estado estable, cuando se corta la conectividad de red entre service-b y PostgreSQL durante 60 segundos, esperamos que las órdenes dejadas en service-a dejen de responder 201, que la tasa de errores de ese flujo supere el 1 % mientras dure el corte y que, al restaurar la conectividad, el health de service-b vuelva a informar la base conectada y las órdenes vuelvan a responder 201."

Solo la hipótesis 1 fue puesta a prueba.

## 5. Diseño de los experimentos

### 5.1 Latencia — ejecutado

| Campo | Valor |
| --- | --- |
| Tipo de fallo | Retraso del tráfico de salida |
| Herramienta | `tc netem`, script `apply-latency.ps1` |
| Componente afectado | service-b, interfaz `eth0` |
| Blast radius | Únicamente ese contenedor |
| Duración | 120 s, de 13:02:12.528 a 13:04:12.544, hora local |
| Condición de abortar | No aplicar la regla si service-b no corre, si falta `tc` o si `eth0` no responde. No hubo aborto por SLO |
| Rollback automático | Al cumplirse el tiempo, o si falla el paso intermedio, se retira la qdisc. El script manual no falla cuando la regla ya no está |
| SLI | Disponibilidad, tasa de errores y p95 |
| Métricas | `http_req_duration`, `http_req_failed`, checks, iteraciones, peticiones/s; histogramas y contadores de órdenes en Prometheus |
| Logs esperados | Órdenes completadas. `SERVICE_B_TIMEOUT` solo si la espera pasa de 5 s |
| Trazas esperadas | Servidor `POST /api/v1/orders`, validación breve y cliente HTTP largo |
| Resultado esperado | Disponibilidad ≥ 99 %, errores < 1 %, p95 unos 200 ms por encima de la base, regreso en ≤ 30 s |

La regla fue:

```text
tc qdisc replace dev eth0 root netem delay 200ms 20ms distribution normal
```

Durante el fallo, la qdisc observada fue `netem` con `delay 200ms  20ms`. Después del rollback volvió a `noqueue`.

`tc` sobre la qdisc raíz de `eth0` retiene los paquetes que salen de service-b. La respuesta HTTP hacia service-a es uno de esos paquetes. También lo son los mensajes hacia PostgreSQL y hacia el Collector. El pedido no es una sola ida y vuelta: hay confirmación de la transacción, una lectura posterior con `refresh` y, si el pool comprueba la conexión, un `SELECT 1`. Cada envío paga 200 ms. El retraso de la orden es la suma, no el valor de un solo paquete. La validación en service-a no entra en esa suma: en las trazas del fallo duró menos de 1 ms.

### 5.2 CPU al 90 % — no ejecutado

| Campo | Valor |
| --- | --- |
| Tipo de fallo | Agotamiento de CPU |
| Herramienta | `stress-ng`, todavía no instalado en la imagen |
| Componente afectado | service-b |
| Blast radius | CPU de service-b. No debe aplicarse a postgres ni a service-a |
| Duración | 120 s |
| Condición de abortar | Parar el proceso si `/health` de service-b deja de responder |
| Rollback automático | El proceso termina y libera la CPU. No queda estado de red |
| SLI | Disponibilidad, errores y p95 |
| Métricas | k6 y `process_cpu_utilization_ratio` de service-b |
| Logs esperados | Procesamiento normal o timeout si la orden supera 5 s |
| Trazas esperadas | `process_order` y la llamada HTTP más largos, sin corte de red |
| Resultado esperado | El de la hipótesis 2. Sin medición |

### 5.3 Partición service-b / PostgreSQL — no ejecutado

| Campo | Valor |
| --- | --- |
| Tipo de fallo | Pérdida de conectividad con la base |
| Herramienta | Diseño conceptual con Gremlin o Litmus. En local sería un bloqueo de red solo hacia `postgres:5432`. Ese bloqueo no se aplicó |
| Componente afectado | Camino service-b → PostgreSQL |
| Blast radius | service-b pierde la base. El resto del laboratorio no debe quedar aislado |
| Duración | 60 s |
| Condición de abortar | Restaurar la ruta si el corte sale de ese camino o si no se puede leer el health |
| Rollback automático | A los 60 s se devuelve la conectividad y se exige `database` = `connected` |
| SLI | Tasa de errores del alta y salud de la base |
| Métricas | Errores de órdenes, `http_req_failed`, respuestas 502 o 504 |
| Logs esperados | Fallo de inserción y, en service-a, no disponibilidad o timeout |
| Trazas esperadas | `process_order` en error |
| Resultado esperado | El de la hipótesis 3. Sin medición |

## 6. Métricas, SLI, logs y trazas

La disponibilidad se lee con checks de k6 que exigen 201 y con el ratio de `app_orders_requests_total` cuyo `result` es `success`. La tasa de errores se lee con `http_req_failed` y con `app_orders_errors_total`. La latencia de referencia es el p95 de k6. Prometheus calcula otro p95 sobre `app_orders_duration_seconds`; sus cubos de 2.5 s y 5 s no separan valores dentro de ese intervalo. El throughput son las peticiones por segundo.

Los logs de la aplicación son JSON e incluyen `request_id` cuando el middleware lo tiene. No se archivó un extracto de Loki de esta ventana. Las trazas sí: 20 operaciones `POST /api/v1/orders` durante la regla, más el cliente `POST` y `validate_order`. Jaeger, en la consulta guardada, solo enumeraba el servicio `service-a`.

## 7. Procedimiento ejecutado

Se recreó service-b con el overlay de caos. Se comprobó el estado estable. Se midió la línea base durante 120 s, sin regla de red. Se lanzó la misma carga otros 120 s y, ya con tráfico, se aplicó `netem` otros 120 s. El script retiró la regla al finalizar. Después se consultaron Prometheus y Jaeger, y se corrió una sonda de recuperación de 30 s.

Esa sonda no arrancó a los 30 s del rollback. El rollback es de las 13:04:12 y el archivo `recovery-20261018-130644.json` corresponde a las 13:06:44.

## 8. Resultados

| Escenario | p95 | Errores | Checks | Peticiones/s |
| --- | ---: | ---: | ---: | ---: |
| Línea base, 120 s | 18.302411 ms | 0 | 100 % | 23.218029 |
| Latencia, 120 s | 2690.823211 ms | 0 | 100 % | 5.729309 |
| Recuperación, 30 s | 18.957767 ms | 0 | 100 % | 23.211206 |

Cifras redondeadas usadas al comunicar el ejercicio: 18.3 ms y 23.22 peticiones/s; 2690.8 ms y 5.73 peticiones/s; 19.0 ms y 23.21 peticiones/s.

Jaeger, solo dentro de la regla, para `POST /api/v1/orders`: mínimo 2486.031 ms, promedio 2658.308 ms, p95 2775.635 ms, máximo 2947.575 ms. El cliente `POST` tiene un p95 de 2765.155 ms. `validate_order` tiene un p95 de 0.260 ms.

Prometheus en la ventana del fallo: p95 4.657609 s, ratio de éxito 1, ratio de errores 0, 3.834983 peticiones/s. En la línea base: p95 0.024260 s, éxito 1, 21.500708 peticiones/s. La consulta de errores de la línea base no devolvió serie. El 4.66 s sale de interpolar el cubo 2.5–5 s; no sustituye a k6 ni a Jaeger.

El promedio k6 del escenario de latencia, 664.997 ms, no es la latencia del fallo. La carga empezó a las 13:01:49 y la regla a las 13:02:12. Las trazas tomadas ya con la regla activa están todas por encima de 2.4 s.

## 9. Cálculos

Sobre los JSON de k6:

- Incremento absoluto del p95: 2690.8232107 − 18.302411 = 2672.520800 ms.
- Incremento porcentual: 14602.02 %.
- Factor: 2690.8232107 / 18.302411 = 147.02.
- Reducción de throughput: 75.32 %.
- Recuperación frente a la base: el p95 sube 0.655356 ms (3.58 %) y el throughput baja 0.006823 peticiones/s (0.029 %).

## 10. Esperado y obtenido

La hipótesis 1 queda parcialmente confirmada.

| Enunciado | Veredicto |
| --- | --- |
| Disponibilidad de al menos el 99 % | Confirmada. Checks al 100 % y ratio de éxito 1 |
| Tasa de errores inferior al 1 % | Confirmada. `http_req_failed` = 0 y, en el fallo, ratio de Prometheus = 0 |
| El p95 aumenta aproximadamente 200 ms | Refutado. El aumento fue 2672.52 ms |
| El sistema vuelve al nivel de la línea base | Observado en la sonda de las 13:06:44, con p95 18.96 ms |
| Ese regreso ocurre antes de 30 s | No demostrado. No hay muestra entre 13:04:12 y 13:04:42 |

Las hipótesis 2 y 3 no tienen veredicto.

## 11. Debilidad que el fallo dejó ver

service-a permanece bloqueado hasta que service-b responde. En la traza, casi todo el tiempo está en esa llamada.

El alta escribe la fila y la vuelve a leer. Además, la comprobación de la conexión puede consultar la base antes de usarla. No es un patrón N+1: no hay un bucle de consultas por elemento. Son pocos viajes, todos secuenciales y todos expuestos al retraso de salida. Eso amplifica 200 ms hasta unos 2.7 s.

Con 5 usuarios el servicio no falló: siguió entregando 201 porque la orden tardaba menos que el timeout de 5 s. El coste apareció como capacidad. El throughput bajó un 75.32 %. A una concurrencia mayor, el mismo mecanismo puede llenar las peticiones en curso y el pool. Este ejercicio no subió de 5 usuarios, así que esa saturación es un riesgo, no una medición.

El límite de tiempo que sí está implementado es el timeout HTTP de 5 s. No hay timeout de comando hacia PostgreSQL. No hay circuit breaker, no hay reintentos en el alta y no hay un tope de concurrencia distinto del pool por defecto. El timeout de 5 s no llegó a actuar.

## 12. Remediaciones propuestas

No están implementadas.

- Mantener el timeout HTTP y agregar un timeout de comando en la sesión de PostgreSQL.
- Abrir el circuito de service-a hacia service-b cuando la dependencia ya no cumple el tiempo.
- Reintentar solo operaciones idempotentes, con tope, backoff y jitter. Este `POST` inserta una fila; reintentarlo puede duplicar la orden si no existe una clave de idempotencia.
- Quitar viajes secuenciales que el código ya hace, en particular `refresh` después de `commit` si el dato no hace falta releerlo, y revisar si `pool_pre_ping` debe seguir activo en este fallo. No se trata de corregir un N+1 inexistente.
- Poner un bulkhead o un máximo de llamadas simultáneas hacia service-b.
- Alertar por p95 y por caída de throughput, no solo por errores. En este Game Day la tasa de errores no se movió.
- Repetir la latencia solo en el segmento service-a → service-b, sin demorar la salida de service-b hacia PostgreSQL, para medir el incremento de 200 ms sin la amplificación de la base.

## 13. Limitaciones

La recuperación anterior a 30 s no tiene evidencia. El p95 de k6 bajo el nombre "latencia" incluye un tramo sano. Jaeger cubre 20 trazas, no todas las órdenes, y no muestra SQL ni service-b. Prometheus agrupa el p95 del fallo en un cubo de 2.5 s. La serie de errores de la línea base está vacía. No hay capturas. CPU y partición no se ejecutaron.

## 14. Conclusiones

Doscientos milisegundos de `netem` en la salida de service-b no produjeron errores y mantuvieron la disponibilidad medida en el 100 %. El p95 de cara al cliente pasó de 18.30 ms a 2690.82 ms y el ritmo de órdenes bajó de 23.22 a 5.73 por segundo. Dentro de la ventana del fallo, Jaeger midió 2775.64 ms de p95, casi por completo en la llamada a service-b. La hipótesis de latencia queda parcialmente confirmada: se sostienen disponibilidad y errores, se rechaza el incremento de unos 200 ms, se observa el regreso al nivel base y no se demuestra que ese regreso ocurriera en menos de 30 s. La ampliación se explica porque `eth0` retrasa cada paquete que service-b envía, tanto la respuesta HTTP como la conversación con PostgreSQL.

## 15. Evidencias

| Archivo | Tipo | Qué demuestra | Dónde usarlo |
| --- | --- | --- | --- |
| `chaos/evidence/baseline-20261018-125909.json` | k6 | p95 18.302411 ms, errores 0, checks 1, 23.218029 peticiones/s | Secciones 3 y 8 |
| `chaos/evidence/latency-20261018-130149.json` | k6 | p95 2690.823211 ms, errores 0, 5.729309 peticiones/s | Secciones 8, 9 y 10 |
| `chaos/evidence/recovery-20261018-130644.json` | k6 | p95 18.957767 ms y 23.211206 peticiones/s a las 13:06:44 | Secciones 8 y 10 |
| `chaos/evidence/jaeger-latency-traces.json` | Trazas | 20 trazas; p95 2775.635 ms; validación < 1 ms | Secciones 6, 8 y 11 |
| `chaos/evidence/jaeger-services.json` | Catálogo | Solo aparece `service-a` | Sección 13 |
| `chaos/evidence/prometheus-baseline-p95.json` | Métrica | p95 0.024259709440708092 s | Sección 8 |
| `chaos/evidence/prometheus-latency-p95.json` | Métrica | p95 4.657608695652174 s | Sección 8 |
| `chaos/evidence/prometheus-latency-buckets.json` | Métrica | Cubo 2.5 s–5 s | Sección 13 |
| `chaos/evidence/prometheus-baseline-success-ratio.json` | Métrica | Éxito = 1 | Sección 10 |
| `chaos/evidence/prometheus-latency-success-ratio.json` | Métrica | Éxito = 1 durante el fallo | Sección 10 |
| `chaos/evidence/prometheus-baseline-error-ratio.json` | Métrica | Sin serie | Sección 13 |
| `chaos/evidence/prometheus-latency-error-ratio.json` | Métrica | Errores = 0 | Sección 10 |
| `chaos/evidence/prometheus-baseline-rps.json` | Métrica | 21.50070829444222 peticiones/s | Sección 8 |
| `chaos/evidence/prometheus-latency-rps.json` | Métrica | 3.8349826947492915 peticiones/s | Sección 8 |
| `chaos/evidence/experiment-report.md` | Bitácora | Cifras, veredictos y diseño de lo no ejecutado | Anexo de laboratorio |

## 16. Capturas que todavía faltan

No se generó el PDF. Faltan estas imágenes para pegarlas en el informe:

1. Docker Compose estable, con los ocho servicios.
2. Health checks de service-a y de service-b.
3. Resultado k6 de la línea base.
4. Regla `tc` activa.
5. Resultado k6 bajo latencia.
6. Traza lenta en Jaeger.
7. Consulta p95 de Prometheus.
8. Rollback, con la qdisc otra vez en `noqueue`.
9. Prueba de recuperación.

Las capturas 4 y 8 ya no están en pantalla: el fallo terminó a las 13:04:12. Repetirlas exigiría ejecutar de nuevo el caos. El texto de ambas qdisc está en la sección 5.1.
