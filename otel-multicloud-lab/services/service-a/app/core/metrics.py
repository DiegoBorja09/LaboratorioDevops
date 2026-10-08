import time
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram, UpDownCounter

_ROUTE = "/api/v1/orders"
_METHOD = "POST"
_BUCKETS_SECONDS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0)

_requests: Counter | None = None
_errors: Counter | None = None
_duration: Histogram | None = None
_in_flight: UpDownCounter | None = None


def _instruments() -> tuple[Counter, Counter, Histogram, UpDownCounter]:
    global _requests, _errors, _duration, _in_flight
    if _requests is None or _errors is None or _duration is None or _in_flight is None:
        meter = metrics.get_meter("service-a")
        _requests = meter.create_counter(
            "app.orders.requests",
            unit="{request}",
            description="Peticiones recibidas en POST /api/v1/orders",
        )
        _errors = meter.create_counter(
            "app.orders.errors",
            unit="{error}",
            description="Peticiones de orden que terminan con error",
        )
        _duration = meter.create_histogram(
            "app.orders.duration",
            unit="s",
            description="Duración de POST /api/v1/orders",
            explicit_bucket_boundaries_advisory=_BUCKETS_SECONDS,
        )
        _in_flight = meter.create_up_down_counter(
            "app.orders.in_flight",
            unit="{request}",
            description="Peticiones de orden en curso",
        )
    return _requests, _errors, _duration, _in_flight


@contextmanager
def track_order_request() -> Iterator[dict[str, int]]:
    requests, errors, duration, in_flight = _instruments()
    base = {
        "http.request.method": _METHOD,
        "http.route": _ROUTE,
    }
    in_flight.add(1, base)
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
        try:
            duration.record(time.perf_counter() - started, outcome)
            requests.add(1, outcome)
            if code >= 400:
                errors.add(1, outcome)
        finally:
            in_flight.add(-1, base)
