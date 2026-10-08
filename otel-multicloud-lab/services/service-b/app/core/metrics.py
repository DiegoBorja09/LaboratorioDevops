import time
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram

_ROUTE = "/api/v1/orders/process"
_METHOD = "POST"
_BUCKETS_SECONDS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0)

_processed: Counter | None = None
_errors: Counter | None = None
_duration: Histogram | None = None


def _instruments() -> tuple[Counter, Counter, Histogram]:
    global _processed, _errors, _duration
    if _processed is None or _errors is None or _duration is None:
        meter = metrics.get_meter("service-b")
        _processed = meter.create_counter(
            "app.orders.processed",
            unit="{order}",
            description="Pedidos almacenados correctamente",
        )
        _errors = meter.create_counter(
            "app.orders.processing.errors",
            unit="{error}",
            description="Fallos de procesamiento o de base de datos",
        )
        _duration = meter.create_histogram(
            "app.orders.processing.duration",
            unit="s",
            description="Duración del procesamiento de un pedido",
            explicit_bucket_boundaries_advisory=_BUCKETS_SECONDS,
        )
    return _processed, _errors, _duration


@contextmanager
def track_processing() -> Iterator[dict[str, int]]:
    processed, errors, duration = _instruments()
    base = {
        "http.request.method": _METHOD,
        "http.route": _ROUTE,
    }
    started = time.perf_counter()
    status = {"code": 500}
    try:
        yield status
    finally:
        code = status["code"]
        outcome = {
            **base,
            "http.response.status_code": code,
            "result": "success" if code < 400 else "error",
        }
        duration.record(time.perf_counter() - started, outcome)
        if code < 400:
            processed.add(1, outcome)
        else:
            errors.add(1, outcome)
