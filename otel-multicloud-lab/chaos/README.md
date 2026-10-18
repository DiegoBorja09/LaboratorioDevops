# Caos: latencia de 200 ms en service-b

El experimento de latencia ya se ejecutó el 2026-10-18. Los resultados y el informe están en `chaos/evidence/experiment-report.md` y en `docs/game-day-plan.md`. Este archivo conserva el procedimiento. No hay que volver a inyectar el fallo para leer esas evidencias. El Compose normal sigue sin `NET_ADMIN` y sin `privileged`.

## Objetivo

Inyectar 200 ms de latencia de red en el contenedor `service-b` con `tc netem`, medir el efecto sobre el flujo real de órdenes y retirar la regla al terminar.

## Arquitectura local

| Servicio | Dirección en el host | Dentro de Compose |
| --- | --- | --- |
| service-a | http://localhost:8081 | `service-a:8080` |
| service-b | http://localhost:8082 | `service-b:8080` |
| postgres | `localhost:5433` | `postgres:5432` |
| Grafana | http://localhost:3000 | — |
| Prometheus | http://localhost:9090 | — |
| Jaeger | http://localhost:16686 | — |
| Loki | http://localhost:3100 | — |
| otel-collector | OTLP `4317` y `4318` | `otel-collector:4317` |

k6 entra por la red Docker `otel-multicloud-lab` y llama a `http://service-a:8080`. El puerto `8081` es solo el del host. La ruta real es `POST /api/v1/orders`. Una orden aceptada responde **201**, no 200. El cuerpo usado por las pruebas de carga ya existentes es:

```json
{"customer_id":"bench-customer","amount":150000.5,"currency":"cop"}
```

Cada iteración envía un `X-Request-ID` UUID distinto. El archivo común de ese flujo es `chaos/k6/orders-flow.js`. `baseline.js` y `latency-experiment.js` lo importan para que la carga y los umbrales no diverjan.

## Hipótesis

En estado estable, cuando se agregan 200 ms de latencia a service-b durante 120 segundos, esperamos que service-a mantenga una disponibilidad mínima del 99 %, una tasa de errores inferior al 1 %, que la latencia p95 aumente aproximadamente 200 ms y que regrese al rango normal máximo 30 segundos después del rollback.

Esta fase guarda las evidencias para contrastar esa hipótesis. No calcula el resultado.

## Estado estable

Los ocho servicios del Compose principal están en ejecución: `service-a`, `service-b`, `postgres`, `grafana`, `prometheus`, `jaeger`, `loki` y `otel-collector`.

- `GET http://localhost:8081/health` responde con estado exitoso y `"status": "healthy"`.
- `GET http://localhost:8082/health` responde con estado exitoso, `"status": "healthy"` y `"database": "connected"`.

`check-steady-state.ps1` solo observa. No aplica ninguna regla de red.

## Blast radius

Únicamente el contenedor `service-b`. La regla es:

```text
tc qdisc replace dev eth0 root netem delay 200ms 20ms distribution normal
```

`tc` en la qdisc raíz de `eth0` retrasa el tráfico que **sale** de service-b. Eso incluye la respuesta HTTP hacia service-a y también las conexiones salientes hacia PostgreSQL y el Collector. El aumento de p95 puede superar los 200 ms por esas salidas adicionales. No se modifican puertos, redes, PostgreSQL ni el stack de observabilidad.

La API sigue corriendo como el usuario `app`. `tc` se ejecuta con `docker compose exec -u root` porque `NET_ADMIN` no autoriza a ese usuario a cambiar la qdisc. El contenedor no usa `privileged`.

## Duración

120 segundos. Al cumplirse, `apply-latency.ps1` ejecuta el rollback aunque el paso anterior haya fallado. `rollback-latency.ps1` también puede lanzarse a mano y no falla si la regla ya no existe.

## Métricas y SLI

k6 mide `http_req_duration` (incluye p95), `http_req_failed`, `checks`, `iterations` y peticiones por segundo.

Umbrales de la línea base y del experimento:

- `http_req_failed` menor que 1 %.
- `checks` iguales o superiores al 99 %. El check exige HTTP 201 en `POST /api/v1/orders`.

Esos umbrales cubren la disponibilidad y la tasa de errores de la hipótesis. El p95 queda en el resumen para compararlo con la línea base; no tumba la prueba por subir ~200 ms.

## Requisitos

- Docker Compose v2 y la red del proyecto `otel-multicloud-lab`.
- PowerShell.
- No hace falta instalar k6 en el host. Los scripts usan la imagen ya fijada en el laboratorio, `grafana/k6:2.3.0`.
- El kernel de Docker debe permitir `sch_netem` en `eth0`.
- El experimento usa el overlay. El Compose de todos los días no lo incluye.

`services/service-b/Dockerfile.chaos` repite el Dockerfile normal y solo agrega el paquete `iproute2`. Docker no puede heredar un Dockerfile hermano. Si cambia el Dockerfile normal, hay que copiar ese cambio al de caos. En el overlay, `context` es `./services/service-b` porque Compose resuelve esa ruta desde el directorio del proyecto, no desde `chaos/`. La imagen de caos se etiqueta `otel-multicloud-lab-service-b:chaos` para no sustituir la imagen del Compose normal.

## Procedimiento

Desde `otel-multicloud-lab`:

1. Levantar el entorno de caos.

```powershell
docker compose -f docker-compose.yml -f chaos/compose.chaos.yml up -d --build
```

2. Comprobar el estado estable.

```powershell
.\chaos\scripts\check-steady-state.ps1
```

El resumen debe terminar en `Estado estable: PASS`.

3. Ejecutar la línea base. No inyecta latencia.

```powershell
.\chaos\scripts\run-baseline.ps1
```

4. Abrir una segunda terminal en el mismo directorio.

5. En la primera terminal, ejecutar la prueba k6 del experimento. Este comando no activa el caos.

```powershell
.\chaos\scripts\run-latency-experiment.ps1
```

6. Cuando k6 ya esté enviando carga, en la segunda terminal activar la latencia durante 120 segundos.

```powershell
.\chaos\scripts\apply-latency.ps1 -DelayMs 200 -JitterMs 20 -DurationSeconds 120
```

Anota las líneas `Latencia iniciada` y `Latencia finalizada`. Al terminar, el script retira la regla.

7. Durante esa ventana revisar:

- Grafana: http://localhost:3000
- Prometheus: http://localhost:9090
- Jaeger: http://localhost:16686
- Loki, vía Grafana o http://localhost:3100

8. Comprobar el rollback. Si la segunda terminal ya terminó, este paso debe decir que no había regla netem y mostrar la qdisc resultante.

```powershell
.\chaos\scripts\rollback-latency.ps1
```

9. Verificar la recuperación. Confirma que no queda netem, repite los health checks y lanza 30 segundos de órdenes.

```powershell
.\chaos\scripts\verify-recovery.ps1
```

Los JSON quedan en `chaos/evidence/` con fecha y hora: `baseline-*.json`, `latency-*.json` y `recovery-*.json`. Esa carpeta está en `.gitignore`, salvo `.gitkeep`.

## Capturas para el informe

- Terminal con `Estado estable: PASS`.
- Resumen k6 de la línea base: p95, `http_req_failed`, `checks`, iteraciones y peticiones por segundo.
- Terminal con el instante de inicio, la regla `tc` y el instante de fin.
- Grafana durante los 120 segundos, con la latencia del flujo de órdenes.
- Jaeger: una traza de `POST /api/v1/orders` que llegue a service-b dentro de la ventana.
- Prometheus: tasa de errores o códigos HTTP de esa ventana.
- Loki: logs de service-a o service-b si aparecen fallos.
- Terminal del rollback con la qdisc de `eth0` ya sin `netem`.
- Resumen k6 del experimento y el de recuperación.

## Gráficas a partir de los JSON

Desde `otel-multicloud-lab`, sin volver a ejecutar el caos:

```powershell
.\.venv\Scripts\python.exe -m pip install -r chaos/requirements-charts.txt
.\.venv\Scripts\python.exe chaos/scripts/generate-evidence-charts.py
```

El script lee los JSON de `chaos/evidence` y escribe PNG en `chaos/evidence/charts`. No modifica los JSON. `matplotlib` queda solo en `chaos/requirements-charts.txt`, fuera de los microservicios. El índice de figuras está en `chaos/evidence/evidence-index.md`.

## Rollback manual

Desde `otel-multicloud-lab`, con el contenedor de caos en marcha:

```powershell
.\chaos\scripts\rollback-latency.ps1
```

Equivale a quitar la qdisc solo si existe:

```powershell
docker compose exec -T -u root service-b tc qdisc del dev eth0 root
docker compose exec -T -u root service-b tc qdisc show dev eth0
```

El segundo comando es la comprobación. Si la regla ya no está, el script de rollback no la vuelve a borrar y termina bien.

## Volver al Compose normal

Recrea solo service-b con el Dockerfile normal, sin `NET_ADMIN`:

```powershell
docker compose -f docker-compose.yml up -d --build service-b
```

El resto de los servicios no se reinicia. A partir de ahí `tc` ya no está en la imagen y el contenedor no tiene la capability. Para levantar el laboratorio completo sin el overlay:

```powershell
docker compose -f docker-compose.yml up -d
```
