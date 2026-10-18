"""Genera las figuras del Game Day a partir de los JSON de chaos/evidence.

No modifica esos JSON. No inventa muestras intermedias.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.patches import Patch

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "chaos" / "evidence"
CHARTS = EVIDENCE / "charts"
LOCAL_TZ = timezone(timedelta(hours=-5))

K6_FILES = (
    ("baseline-20261018-125909.json", "Línea base"),
    ("latency-20261018-130149.json", "Latencia"),
    ("recovery-20261018-130644.json", "Recuperación"),
)
COLORS = ("#1f4e79", "#b85c38", "#2e7d32")
WIDTH_PX = 1600
HEIGHT_PX = 900
DPI = 120


def load_json(name: str) -> dict:
    path = EVIDENCE / name
    if not path.is_file():
        raise FileNotFoundError(f"No está el JSON de evidencia: {path}")
    return json.loads(path.read_text(encoding="utf-8-sig"))


def require_number(payload: dict, key: str, source: str) -> float:
    if key not in payload:
        raise KeyError(f"{source} no trae {key}")
    value = payload[key]
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{source}.{key} no es numérico")
    return float(value)


def prom_value(name: str) -> tuple[datetime, float] | None:
    payload = load_json(name)
    result = payload.get("data", {}).get("result", [])
    if not result:
        return None
    raw_time, raw_value = result[0]["value"]
    instant = datetime.fromtimestamp(int(raw_time), tz=timezone.utc).astimezone(LOCAL_TZ)
    return instant, float(raw_value)


def chaos_window() -> tuple[datetime, datetime] | None:
    report = EVIDENCE / "experiment-report.md"
    if not report.is_file():
        return None
    text = report.read_text(encoding="utf-8")
    match = re.search(
        r"Inicio (?P<start>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})"
        r"\. Fin (?P<end>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d+[+-]\d{2}:\d{2})",
        text,
    )
    if not match:
        return None
    return _parse_local_iso(match.group("start")), _parse_local_iso(match.group("end"))


def _parse_local_iso(value: str) -> datetime:
    head, fraction_and_tz = value.split(".", 1)
    fraction = fraction_and_tz[:6]
    tz_text = fraction_and_tz[-6:]
    parsed = datetime.strptime(f"{head}.{fraction}{tz_text}", "%Y-%m-%dT%H:%M:%S.%f%z")
    return parsed.astimezone(LOCAL_TZ)


def configure_style() -> None:
    plt.rcParams.update(
        {
            "font.family": "DejaVu Sans",
            "font.size": 14,
            "axes.titlesize": 20,
            "axes.titleweight": "semibold",
            "axes.labelsize": 16,
            "xtick.labelsize": 14,
            "ytick.labelsize": 14,
            "figure.facecolor": "white",
            "savefig.facecolor": "white",
            "axes.facecolor": "white",
            "text.color": "#1a1a1a",
            "axes.labelcolor": "#1a1a1a",
            "xtick.color": "#1a1a1a",
            "ytick.color": "#1a1a1a",
            "axes.edgecolor": "#333333",
        }
    )


def new_figure():
    fig, ax = plt.subplots(figsize=(WIDTH_PX / DPI, HEIGHT_PX / DPI), dpi=DPI)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")
    return fig, ax


def save(fig: plt.Figure, name: str) -> Path:
    CHARTS.mkdir(parents=True, exist_ok=True)
    destination = CHARTS / name
    fig.savefig(destination, dpi=DPI, bbox_inches=None, facecolor="white")
    plt.close(fig)
    return destination


def load_k6() -> list[dict]:
    rows = []
    for filename, label in K6_FILES:
        payload = load_json(filename)
        rows.append(
            {
                "label": label,
                "file": filename,
                "p95_ms": require_number(payload, "http_req_duration_p95", filename),
                "avg_ms": require_number(payload, "http_req_duration_avg", filename),
                "errors": require_number(payload, "http_req_failed_rate", filename),
                "checks": require_number(payload, "checks_rate", filename),
                "rps": require_number(payload, "requests_per_second", filename),
                "iterations": require_number(payload, "iterations", filename),
            }
        )
    return rows


def style_axes(ax: plt.Axes) -> None:
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#d0d0d0", linewidth=0.8)
    ax.set_axisbelow(True)


def label_bars(ax: plt.Axes, bars, texts: list[str]) -> None:
    for bar, text in zip(bars, texts):
        height = bar.get_height()
        ax.annotate(
            text,
            xy=(bar.get_x() + bar.get_width() / 2, height),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=14,
            color="#1a1a1a",
        )


def chart_latency(rows: list[dict]) -> None:
    fig, ax = new_figure()
    labels = [row["label"] for row in rows]
    values = [row["p95_ms"] for row in rows]
    bars = ax.bar(labels, values, color=COLORS, width=0.62)
    label_bars(ax, bars, [f"{value:.1f} ms" for value in values])
    ax.set_title("Latencia p95 de POST /api/v1/orders")
    ax.set_ylabel("p95 de http_req_duration (ms)")
    ax.set_ylim(0, max(values) * 1.18)
    style_axes(ax)
    fig.text(
        0.01,
        0.01,
        "Fuente: JSON de k6 en chaos/evidence. Una barra por escenario; no hay serie temporal.",
        fontsize=11,
        color="#333333",
    )
    save(fig, "latency-comparison.png")


def chart_throughput(rows: list[dict]) -> None:
    fig, ax = new_figure()
    labels = [row["label"] for row in rows]
    values = [row["rps"] for row in rows]
    bars = ax.bar(labels, values, color=COLORS, width=0.62)
    label_bars(ax, bars, [f"{value:.2f}" for value in values])
    ax.set_title("Peticiones por segundo")
    ax.set_ylabel("Peticiones por segundo")
    ax.set_ylim(0, max(values) * 1.22)
    style_axes(ax)
    fig.text(
        0.01,
        0.01,
        "Fuente: requests_per_second de los tres JSON de k6. No se interpolan instantes.",
        fontsize=11,
        color="#333333",
    )
    save(fig, "throughput-comparison.png")


def chart_availability(rows: list[dict]) -> None:
    fig, ax = new_figure()
    labels = [row["label"] for row in rows]
    positions = list(range(len(rows)))
    width = 0.36
    checks = [row["checks"] * 100 for row in rows]
    errors = [row["errors"] * 100 for row in rows]
    checks_bars = ax.bar(
        [pos - width / 2 for pos in positions],
        checks,
        width=width,
        color="#1f4e79",
        label="Checks exitosos (%)",
    )
    error_bars = ax.bar(
        [pos + width / 2 for pos in positions],
        errors,
        width=width,
        color="#b85c38",
        label="Errores HTTP (%)",
    )
    label_bars(ax, checks_bars, [f"{value:.0f} %" for value in checks])
    for bar, value in zip(error_bars, errors):
        ax.annotate(
            f"{value:.0f} %",
            xy=(bar.get_x() + bar.get_width() / 2, max(value, 0)),
            xytext=(0, 8),
            textcoords="offset points",
            ha="center",
            va="bottom",
            fontsize=14,
        )
    ax.set_xticks(positions, labels)
    ax.set_ylim(0, 125)
    ax.set_ylabel("Porcentaje")
    ax.set_title("Disponibilidad y tasa de errores")
    ax.legend(frameon=False, loc="upper right")
    style_axes(ax)
    baseline_errors = prom_value("prometheus-baseline-error-ratio.json")
    error_note = (
        "Prometheus, ratio de errores de la línea base: no disponible (la consulta no devolvió serie)."
        if baseline_errors is None
        else "Prometheus, ratio de errores de la línea base: presente en el JSON."
    )
    fig.text(
        0.01,
        0.01,
        "Fuente: checks_rate y http_req_failed_rate de k6. " + error_note,
        fontsize=11,
        color="#333333",
    )
    save(fig, "availability-comparison.png")


def chart_prometheus() -> None:
    fig, ax = new_figure()
    points = []
    for filename, label in (
        ("prometheus-baseline-p95.json", "Consulta de línea base"),
        ("prometheus-latency-p95.json", "Consulta del fallo"),
    ):
        sample = prom_value(filename)
        if sample is None:
            raise ValueError(f"{filename} no trae un valor de p95")
        points.append((label, filename, sample[0], sample[1] * 1000))

    window = chaos_window()
    if window is not None:
        start, end = window
        ax.axvspan(start, end, color="#f4c7b8", alpha=0.85, zorder=0)
    times = [item[2] for item in points]
    values = [item[3] for item in points]
    ax.scatter(times, values, s=120, color="#1f4e79", zorder=3)
    for label, _filename, instant, value_ms in points:
        ax.annotate(
            f"{label}\n{value_ms:.1f} ms\n{instant.strftime('%H:%M:%S')}",
            xy=(instant, value_ms),
            xytext=(12, 12),
            textcoords="offset points",
            fontsize=13,
            color="#1a1a1a",
        )
    ax.set_title("p95 de Prometheus: solo dos consultas instantáneas")
    ax.set_ylabel("p95 de app_orders_duration_seconds (ms)")
    ax.set_xlabel("Hora local (UTC−5)")
    upper = max(values) * 1.28
    ax.set_ylim(0, upper)
    fig.autofmt_xdate()
    style_axes(ax)
    if window is None:
        window_note = "Ventana de caos: no disponible en los JSON."
        handles = []
    else:
        window_note = (
            "La banda marca el inicio y el fin escritos en experiment-report.md. "
            "No es una muestra de Prometheus."
        )
        handles = [Patch(facecolor="#f4c7b8", edgecolor="#b85c38", label="Ventana de caos (bitácora)")]
        ax.legend(handles=handles, frameon=False, loc="upper left")
    fig.text(
        0.01,
        0.01,
        "No se dibuja una línea: no hay puntos intermedios en los JSON. " + window_note,
        fontsize=11,
        color="#333333",
    )
    save(fig, "prometheus-p95-timeline.png")


def chart_summary(rows: list[dict]) -> None:
    baseline, latency, recovery = rows
    delta_ms = latency["p95_ms"] - baseline["p95_ms"]
    factor = latency["p95_ms"] / baseline["p95_ms"]
    throughput_drop = (baseline["rps"] - latency["rps"]) / baseline["rps"] * 100
    cell_text = []
    for row in rows:
        cell_text.append(
            [
                row["label"],
                f"{row['p95_ms']:.1f} ms",
                f"{row['errors'] * 100:.0f} %",
                f"{row['checks'] * 100:.0f} %",
                f"{row['rps']:.2f}",
            ]
        )
    fig, ax = new_figure()
    ax.axis("off")
    ax.set_title("Resultados del experimento de latencia", pad=24)
    table = ax.table(
        cellText=cell_text,
        colLabels=["Escenario", "p95", "Errores", "Checks", "Peticiones/s"],
        loc="center",
        cellLoc="center",
    )
    table.auto_set_font_size(False)
    table.set_fontsize(15)
    table.scale(1, 2.4)
    for (row_index, _col_index), cell in table.get_celld().items():
        cell.set_edgecolor("#333333")
        cell.set_linewidth(0.8)
        if row_index == 0:
            cell.set_facecolor("#1f4e79")
            cell.set_text_props(color="white", fontweight="semibold")
        elif row_index == 2:
            cell.set_facecolor("#f8ebe6")
        else:
            cell.set_facecolor("white")
        cell.set_height(0.12)
    fig.text(
        0.08,
        0.22,
        (
            f"Incremento del p95: {delta_ms:.1f} ms, aproximadamente {factor:.0f} veces "
            f"la línea base ({factor:.2f})."
        ),
        fontsize=16,
        color="#1a1a1a",
    )
    fig.text(
        0.08,
        0.16,
        f"El throughput disminuyó aproximadamente {throughput_drop:.1f} %.",
        fontsize=16,
        color="#1a1a1a",
    )
    fig.text(
        0.08,
        0.08,
        (
            "Cifras redondeadas desde los tres JSON de k6. "
            f"Recuperación menos línea base: p95 {recovery['p95_ms'] - baseline['p95_ms']:+.1f} ms."
        ),
        fontsize=12,
        color="#333333",
    )
    save(fig, "experiment-summary.png")


def main() -> None:
    configure_style()
    rows = load_k6()
    chart_latency(rows)
    chart_throughput(rows)
    chart_availability(rows)
    chart_prometheus()
    chart_summary(rows)
    print(f"Figuras escritas en {CHARTS}")


if __name__ == "__main__":
    main()
