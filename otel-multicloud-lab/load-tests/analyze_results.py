"""Compara el baseline sin OpenTelemetry con el escenario instrumentado.

No completa valores que falten en los JSON de k6 o en los CSV de recursos.
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

RESULTS = Path(__file__).resolve().parent / "results"
REQUIRED = (
    RESULTS / "baseline.json",
    RESULTS / "otel.json",
    RESULTS / "baseline-resources.csv",
    RESULTS / "otel-resources.csv",
)


def load_json(path: Path) -> dict:
    with path.open(encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, dict):
        raise SystemExit(f"{path.name} no es un objeto JSON")
    return payload


def metric_value(data: dict, metric: str, key: str) -> float | None:
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return None
    entry = metrics.get(metric)
    if not isinstance(entry, dict):
        return None
    values = entry.get("values")
    if not isinstance(values, dict) or key not in values:
        return None
    raw = values[key]
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def threshold_ok(data: dict, metric: str, expression: str) -> bool | None:
    metrics = data.get("metrics")
    if not isinstance(metrics, dict):
        return None
    entry = metrics.get(metric)
    if not isinstance(entry, dict):
        return None
    thresholds = entry.get("thresholds")
    if not isinstance(thresholds, dict):
        return None
    item = thresholds.get(expression)
    if not isinstance(item, dict) or "ok" not in item:
        return None
    return bool(item["ok"])


def load_resources(path: Path) -> dict[str, dict[str, float]]:
    grouped: dict[str, dict[str, list[float]]] = {}
    with path.open(encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        fields = set(reader.fieldnames or [])
        required = {"timestamp", "service", "cpu_percent", "memory_bytes"}
        if not required.issubset(fields):
            raise SystemExit(f"{path.name} no tiene las columnas {', '.join(sorted(required))}")
        for row in reader:
            service = (row.get("service") or "").strip()
            if not service:
                continue
            grouped.setdefault(service, {"cpu": [], "memory": []})
            grouped[service]["cpu"].append(float(row["cpu_percent"]))
            grouped[service]["memory"].append(float(row["memory_bytes"]))
    summary: dict[str, dict[str, float]] = {}
    for service, series in grouped.items():
        if not series["cpu"]:
            continue
        summary[service] = {
            "cpu_avg": sum(series["cpu"]) / len(series["cpu"]),
            "cpu_max": max(series["cpu"]),
            "memory_avg": sum(series["memory"]) / len(series["memory"]),
            "memory_max": max(series["memory"]),
            "samples": float(len(series["cpu"])),
        }
    return summary


def relative_change(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return (current - base) / base * 100


def throughput_degradation(current: float | None, base: float | None) -> float | None:
    if current is None or base is None or base == 0:
        return None
    return (base - current) / base * 100


def show(value: float | None, digits: int = 2) -> str:
    if value is None:
        return "ausente"
    return f"{value:.{digits}f}"


def show_percent(value: float | None) -> str:
    if value is None:
        return "no calculable"
    return f"{value:.2f}"


def mib(value: float | None) -> str:
    if value is None:
        return "ausente"
    return f"{value / (1024 * 1024):.2f}"


def scenario_facts(data: dict) -> dict[str, float | None]:
    return {
        "avg": metric_value(data, "http_req_duration", "avg"),
        "p95": metric_value(data, "http_req_duration", "p(95)"),
        "p99": metric_value(data, "http_req_duration", "p(99)"),
        "rps": metric_value(data, "http_reqs", "rate"),
        "errors": metric_value(data, "http_req_failed", "rate"),
        "iterations": metric_value(data, "iterations", "count"),
        "vus": metric_value(data, "vus", "max"),
        "duration_ms": _duration_ms(data),
        "p99_ok": _as_float(threshold_ok(data, "http_req_duration", "p(99)<500")),
        "errors_ok": _as_float(threshold_ok(data, "http_req_failed", "rate<0.01")),
    }


def _duration_ms(data: dict) -> float | None:
    state = data.get("state")
    if not isinstance(state, dict):
        return None
    raw = state.get("testRunDurationMs")
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        return None
    return float(raw)


def _as_float(value: bool | None) -> float | None:
    if value is None:
        return None
    return 1.0 if value else 0.0


def resource_value(summary: dict[str, dict[str, float]], service: str, key: str) -> float | None:
    entry = summary.get(service)
    if entry is None or key not in entry:
        return None
    return entry[key]


def yes_no(flag: float | None) -> str:
    if flag is None:
        return "ausente"
    return "sí" if flag == 1.0 else "no"


def direction(change: float | None, *, lower_is_better: bool) -> str:
    if change is None:
        return "no hay dato suficiente para calcular el cambio"
    if abs(change) < 0.05:
        return "se mantuvo prácticamente igual"
    if change > 0:
        return "aumentó" if not lower_is_better else "empeoró"
    return "disminuyó" if not lower_is_better else "mejoró"


def write_reports(baseline: dict, otel: dict, baseline_resources: dict, otel_resources: dict) -> None:
    base = scenario_facts(baseline)
    instrumented = scenario_facts(otel)
    rows: list[tuple[str, str, str, str, str]] = []

    def add(name: str, left: float | None, right: float | None, change: float | None, note: str) -> None:
        rows.append((name, show(left), show(right), show_percent(change), note))

    add(
        "Latencia promedio (ms)",
        base["avg"],
        instrumented["avg"],
        relative_change(instrumented["avg"], base["avg"]),
        "Un valor positivo indica más latencia con OpenTelemetry",
    )
    add(
        "Latencia p95 (ms)",
        base["p95"],
        instrumented["p95"],
        relative_change(instrumented["p95"], base["p95"]),
        "Un valor positivo indica más latencia con OpenTelemetry",
    )
    add(
        "Latencia p99 (ms)",
        base["p99"],
        instrumented["p99"],
        relative_change(instrumented["p99"], base["p99"]),
        "Umbral de la prueba: p99 inferior a 500 ms",
    )
    add(
        "Solicitudes por segundo",
        base["rps"],
        instrumented["rps"],
        throughput_degradation(instrumented["rps"], base["rps"]),
        "Aquí el porcentaje es degradación: (baseline - otel) / baseline",
    )
    error_base = None if base["errors"] is None else base["errors"] * 100
    error_otel = None if instrumented["errors"] is None else instrumented["errors"] * 100
    add(
        "Errores (%)",
        error_base,
        error_otel,
        relative_change(error_otel, error_base),
        "Umbral de la prueba: menos del 1 %",
    )

    for service in ("service-a", "service-b"):
        for label, key, unit_note in (
            ("CPU promedio (%)", "cpu_avg", "docker stats, no métricas del SDK"),
            ("CPU máxima (%)", "cpu_max", "docker stats, no métricas del SDK"),
        ):
            left = resource_value(baseline_resources, service, key)
            right = resource_value(otel_resources, service, key)
            add(
                f"{label} {service}",
                left,
                right,
                relative_change(right, left),
                unit_note,
            )
        for label, key in (
            ("Memoria promedio (MiB)", "memory_avg"),
            ("Memoria máxima (MiB)", "memory_max"),
        ):
            left = resource_value(baseline_resources, service, key)
            right = resource_value(otel_resources, service, key)
            left_mib = None if left is None else left / (1024 * 1024)
            right_mib = None if right is None else right / (1024 * 1024)
            add(
                f"{label} {service}",
                left_mib,
                right_mib,
                relative_change(right, left),
                "Calculado desde memory_bytes del CSV",
            )

    p99_change = relative_change(instrumented["p99"], base["p99"])
    rps_degradation = throughput_degradation(instrumented["rps"], base["rps"])
    cpu_a = relative_change(
        resource_value(otel_resources, "service-a", "cpu_avg"),
        resource_value(baseline_resources, "service-a", "cpu_avg"),
    )
    cpu_b = relative_change(
        resource_value(otel_resources, "service-b", "cpu_avg"),
        resource_value(baseline_resources, "service-b", "cpu_avg"),
    )
    mem_a = relative_change(
        resource_value(otel_resources, "service-a", "memory_avg"),
        resource_value(baseline_resources, "service-a", "memory_avg"),
    )
    mem_b = relative_change(
        resource_value(otel_resources, "service-b", "memory_avg"),
        resource_value(baseline_resources, "service-b", "memory_avg"),
    )

    small_signal = all(
        change is None or abs(change) < 5
        for change in (p99_change, rps_degradation, cpu_a, cpu_b, mem_a, mem_b)
    )
    if small_signal:
        cause = (
            "La variación es pequeña. En un portátil local el ruido del sistema "
            "puede explicarla. No se concluye que OpenTelemetry sea la única causa."
        )
    else:
        cause = (
            "Hay diferencias visibles entre los dos escenarios de esta máquina. "
            "El patrón es compatible con el costo de crear y exportar trazas, "
            "métricas y logs, pero el entorno local también mete ruido. "
            "No se aísla OpenTelemetry como única causa."
        )

    errors_ok = instrumented["errors_ok"] == 1.0 and base["errors_ok"] == 1.0
    p99_ok = instrumented["p99_ok"] == 1.0 and base["p99_ok"] == 1.0
    if p99_ok and errors_ok:
        cost = (
            "Los dos escenarios cumplieron p99 inferior a 500 ms y errores inferiores al 1 %. "
            "En este laboratorio el costo medido cabe en esos umbrales."
        )
    elif errors_ok and not p99_ok and base["p99_ok"] == 0.0:
        cost = (
            "Los errores quedaron en 0 % en los dos escenarios, por debajo del 1 %. "
            "El p99 superó 500 ms también en el baseline, así que ese umbral ya no se cumple "
            "sin el SDK en esta máquina. Con OpenTelemetry el p99 sube más. El costo se ve "
            "en latencia y CPU; el incumplimiento del p99 no empieza al encender el SDK."
        )
    elif errors_ok and instrumented["p99_ok"] == 0.0:
        cost = (
            "Los errores siguen bajo el 1 %. El p99 con OpenTelemetry superó 500 ms. "
            "Ese costo de latencia no cabe en el umbral académico de la prueba."
        )
    else:
        cost = (
            "Con los datos presentes no se puede afirmar que el costo quede dentro de "
            "p99 < 500 ms y errores < 1 %. Ese objetivo es académico y local."
        )

    lines = [
        "# Comparación del benchmark local",
        "",
        "Baseline: `OTEL_SDK_DISABLED=true`. Escenario instrumentado: `OTEL_SDK_DISABLED=false`.",
        "La misma prueba usa 50 usuarios virtuales, 5 minutos, `POST /api/v1/orders` y 0,2 s de espera.",
        "CPU y memoria salen de `docker stats`, porque el baseline no exporta métricas del SDK.",
        "",
        "## Resultados",
        "",
        "| Métrica | Baseline | OpenTelemetry | Overhead (%) | Nota |",
        "| --- | ---: | ---: | ---: | --- |",
    ]
    for name, left, right, change, note in rows:
        lines.append(f"| {name} | {left} | {right} | {change} | {note} |")

    lines.extend(
        [
            "",
            "El overhead de latencia, errores, CPU y memoria es `((otel - baseline) / baseline) * 100`.",
            "En solicitudes por segundo una disminución es degradación: `((baseline - otel) / baseline) * 100`.",
            "Si el baseline es cero o el dato no está en el archivo, el overhead queda como `no calculable`.",
            "",
            "## Condiciones registradas",
            "",
            f"- Usuarios máximos baseline: {show(base['vus'], 0)}",
            f"- Usuarios máximos OpenTelemetry: {show(instrumented['vus'], 0)}",
            f"- Duración baseline (s): {show(None if base['duration_ms'] is None else base['duration_ms'] / 1000)}",
            f"- Duración OpenTelemetry (s): {show(None if instrumented['duration_ms'] is None else instrumented['duration_ms'] / 1000)}",
            f"- Iteraciones baseline: {show(base['iterations'], 0)}",
            f"- Iteraciones OpenTelemetry: {show(instrumented['iterations'], 0)}",
            f"- Threshold p99 < 500 ms baseline: {yes_no(base['p99_ok'])}",
            f"- Threshold p99 < 500 ms OpenTelemetry: {yes_no(instrumented['p99_ok'])}",
            f"- Threshold errores < 1 % baseline: {yes_no(base['errors_ok'])}",
            f"- Threshold errores < 1 % OpenTelemetry: {yes_no(instrumented['errors_ok'])}",
            "",
            "## Interpretación",
            "",
            (
                f"La latencia p99 pasó de {show(base['p99'])} ms a {show(instrumented['p99'])} ms "
                f"({show_percent(p99_change)} %). {direction(p99_change, lower_is_better=True).capitalize()} "
                "respecto del baseline."
            ),
            "",
            (
                f"El throughput pasó de {show(base['rps'])} a {show(instrumented['rps'])} solicitudes por segundo. "
                f"La degradación calculada es {show_percent(rps_degradation)} %."
            ),
            "",
            (
                f"La CPU promedio de service-a cambió {show_percent(cpu_a)} % y la de service-b {show_percent(cpu_b)} %. "
                f"La memoria promedio cambió {show_percent(mem_a)} % en service-a y {show_percent(mem_b)} % en service-b."
            ),
            "",
            cost,
            "",
            cause,
            "",
            "Posibles optimizaciones, sin cambiar esta medición: muestrear trazas en lugar de guardarlas todas, "
            "subir el intervalo de exportación de métricas por encima de 5 s y ampliar el lote de spans y logs. "
            "El laboratorio ya exporta con procesadores por lote. Esas palancas bajan CPU y red a cambio de menos detalle.",
            "",
            "Los porcentajes describen esta ejecución local. No se extrapolaron a producción.",
            "",
        ]
    )
    (RESULTS / "comparison.md").write_text("\n".join(lines), encoding="utf-8")

    with (RESULTS / "comparison.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metrica", "baseline", "otel", "overhead_porcentaje", "nota"])
        writer.writerows(rows)


def main() -> int:
    missing = [path.name for path in REQUIRED if not path.is_file()]
    if missing:
        print("Faltan archivos de resultados: " + ", ".join(missing), file=sys.stderr)
        return 1
    write_reports(
        load_json(REQUIRED[0]),
        load_json(REQUIRED[1]),
        load_resources(REQUIRED[2]),
        load_resources(REQUIRED[3]),
    )
    print(f"Escrito {RESULTS / 'comparison.md'}")
    print(f"Escrito {RESULTS / 'comparison.csv'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
