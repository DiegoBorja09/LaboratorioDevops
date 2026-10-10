# Comparación del benchmark local

Baseline: `OTEL_SDK_DISABLED=true`. Escenario instrumentado: `OTEL_SDK_DISABLED=false`.
La misma prueba usa 50 usuarios virtuales, 5 minutos, `POST /api/v1/orders` y 0,2 s de espera.
CPU y memoria salen de `docker stats`, porque el baseline no exporta métricas del SDK.

## Resultados

| Métrica | Baseline | OpenTelemetry | Overhead (%) | Nota |
| --- | ---: | ---: | ---: | --- |
| Latencia promedio (ms) | 256.72 | 321.60 | 25.27 | Un valor positivo indica más latencia con OpenTelemetry |
| Latencia p95 (ms) | 448.27 | 619.27 | 38.15 | Un valor positivo indica más latencia con OpenTelemetry |
| Latencia p99 (ms) | 538.52 | 822.78 | 52.78 | Umbral de la prueba: p99 inferior a 500 ms |
| Solicitudes por segundo | 109.21 | 95.66 | 12.41 | Aquí el porcentaje es degradación: (baseline - otel) / baseline |
| Errores (%) | 0.00 | 0.00 | no calculable | Umbral de la prueba: menos del 1 % |
| CPU promedio (%) service-a | 57.21 | 71.00 | 24.12 | docker stats, no métricas del SDK |
| CPU máxima (%) service-a | 97.52 | 98.71 | 1.22 | docker stats, no métricas del SDK |
| Memoria promedio (MiB) service-a | 61.77 | 68.92 | 11.58 | Calculado desde memory_bytes del CSV |
| Memoria máxima (MiB) service-a | 74.38 | 81.43 | 9.48 | Calculado desde memory_bytes del CSV |
| CPU promedio (%) service-b | 91.95 | 98.27 | 6.88 | docker stats, no métricas del SDK |
| CPU máxima (%) service-b | 123.24 | 128.04 | 3.89 | docker stats, no métricas del SDK |
| Memoria promedio (MiB) service-b | 98.85 | 87.00 | -11.99 | Calculado desde memory_bytes del CSV |
| Memoria máxima (MiB) service-b | 111.50 | 98.80 | -11.39 | Calculado desde memory_bytes del CSV |

El overhead de latencia, errores, CPU y memoria es `((otel - baseline) / baseline) * 100`.
En solicitudes por segundo una disminución es degradación: `((baseline - otel) / baseline) * 100`.
Si el baseline es cero o el dato no está en el archivo, el overhead queda como `no calculable`.

## Condiciones registradas

- Usuarios máximos baseline: 50
- Usuarios máximos OpenTelemetry: 50
- Duración baseline (s): 300.32
- Duración OpenTelemetry (s): 300.45
- Iteraciones baseline: 32798
- Iteraciones OpenTelemetry: 28740
- Threshold p99 < 500 ms baseline: no
- Threshold p99 < 500 ms OpenTelemetry: no
- Threshold errores < 1 % baseline: sí
- Threshold errores < 1 % OpenTelemetry: sí

## Interpretación

La latencia p99 pasó de 538.52 ms a 822.78 ms (52.78 %). Empeoró respecto del baseline.

El throughput pasó de 109.21 a 95.66 solicitudes por segundo. La degradación calculada es 12.41 %.

La CPU promedio de service-a cambió 24.12 % y la de service-b 6.88 %. La memoria promedio cambió 11.58 % en service-a y -11.99 % en service-b.

Los errores quedaron en 0 % en los dos escenarios, por debajo del 1 %. El p99 superó 500 ms también en el baseline, así que ese umbral ya no se cumple sin el SDK en esta máquina. Con OpenTelemetry el p99 sube más. El costo se ve en latencia y CPU; el incumplimiento del p99 no empieza al encender el SDK.

Hay diferencias visibles entre los dos escenarios de esta máquina. El patrón es compatible con el costo de crear y exportar trazas, métricas y logs, pero el entorno local también mete ruido. No se aísla OpenTelemetry como única causa.

Posibles optimizaciones, sin cambiar esta medición: muestrear trazas en lugar de guardarlas todas, subir el intervalo de exportación de métricas por encima de 5 s y ampliar el lote de spans y logs. El laboratorio ya exporta con procesadores por lote. Esas palancas bajan CPU y red a cambio de menos detalle.

Los porcentajes describen esta ejecución local. No se extrapolaron a producción.
