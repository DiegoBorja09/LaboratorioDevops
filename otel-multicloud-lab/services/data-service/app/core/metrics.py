import time
from collections.abc import Iterator
from contextlib import contextmanager

from opentelemetry import metrics
from opentelemetry.metrics import Counter, Histogram

_BUCKETS_SECONDS = (0.005, 0.01, 0.025, 0.05, 0.075, 0.1, 0.25, 0.5, 0.75, 1.0, 2.5, 5.0, 10.0)

_requests: Counter | None = None
_duration: Histogram | None = None
_database_operations: Counter | None = None
_replication_failures: Counter | None = None
_chaos_injections: Counter | None = None


def _instruments() -> tuple[Counter, Histogram, Counter, Counter, Counter]:
    global _requests, _duration, _database_operations, _replication_failures, _chaos_injections
    if (
        _requests is None
        or _duration is None
        or _database_operations is None
        or _replication_failures is None
        or _chaos_injections is None
    ):
        meter = metrics.get_meter("data-service")
        _requests = meter.create_counter(
            "app.data_service.requests",
            description="Solicitudes de replicación y de readiness",
        )
        _duration = meter.create_histogram(
            "app.data_service.request.duration",
            unit="s",
            description="Duración de las solicitudes de data-service",
            explicit_bucket_boundaries_advisory=_BUCKETS_SECONDS,
        )
        _database_operations = meter.create_counter(
            "app.data_service.database.operations",
            description="Operaciones contra Cloud SQL y RDS",
        )
        _replication_failures = meter.create_counter(
            "app.data_service.replication.failures",
            description="Replicaciones que no pudieron completarse en ambas bases",
        )
        _chaos_injections = meter.create_counter(
            "app.data_service.chaos.injections",
            description="Errores inyectados por el caos controlado",
        )
    return _requests, _duration, _database_operations, _replication_failures, _chaos_injections


def reset_instruments() -> None:
    global _requests, _duration, _database_operations, _replication_failures, _chaos_injections
    _requests = None
    _duration = None
    _database_operations = None
    _replication_failures = None
    _chaos_injections = None


@contextmanager
def track_request(operation: str) -> Iterator[dict[str, str]]:
    requests, duration, _database_operations, _replication_failures, _chaos_injections = _instruments()
    started = time.perf_counter()
    status = {"result": "error"}
    try:
        yield status
    finally:
        attributes = {"operation": operation, "result": status["result"]}
        duration.record(max(time.perf_counter() - started, 0), attributes)
        requests.add(1, attributes)


def record_database_operation(cloud: str, operation: str, result: str) -> None:
    _database_operations_counter = _instruments()[2]
    _database_operations_counter.add(
        1,
        {"cloud": cloud, "operation": operation, "result": result},
    )


def record_replication_failure(cloud: str) -> None:
    _instruments()[3].add(1, {"cloud": cloud})


def record_chaos_injection() -> None:
    _instruments()[4].add(1, {"operation": "replicate"})
