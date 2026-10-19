import logging

import pytest
from opentelemetry import trace
from opentelemetry.sdk.metrics.export import MetricExportResult
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind
from opentelemetry.util._once import Once

import app.core.telemetry as telemetry
from app.core.database_spans import DatabaseSemanticSpanProcessor
from app.core.logging import JsonFormatter
from app.core.metrics import (
    record_chaos_injection,
    record_database_operation,
    record_replication_failure,
    reset_instruments,
    track_request,
)
from app.main import create_app
from tests.conftest import EVENT, REQUEST_ID, TOKEN, build_settings
from tests.fakes import Clock, FakeAuditStore

INCOMING_TRACE_ID = "0123456789abcdef0123456789abcdef"
INCOMING_SPAN_ID = "0123456789abcdef"
INCOMING_TRACEPARENT = f"00-{INCOMING_TRACE_ID}-{INCOMING_SPAN_ID}-01"


class _MetricExporter:
    _preferred_temporality: dict[object, object] = {}
    _preferred_aggregation: dict[object, object] = {}

    def export(self, metrics_data: object, **kwargs: object) -> MetricExportResult:
        del metrics_data, kwargs
        return MetricExportResult.SUCCESS

    def shutdown(self, timeout_millis: float = 30000, **kwargs: object) -> None:
        del timeout_millis, kwargs

    def force_flush(self, timeout_millis: float = 30000) -> bool:
        del timeout_millis
        return True


class _LogExporter:
    def export(self, batch: object, **kwargs: object) -> None:
        del batch, kwargs

    def shutdown(self, timeout_millis: float = 30000, **kwargs: object) -> None:
        del timeout_millis, kwargs

    def force_flush(self, timeout_millis: float = 30000) -> bool:
        del timeout_millis
        return True


def test_database_spans_use_current_semantic_conventions(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(DatabaseSemanticSpanProcessor())
    provider.add_span_processor(SimpleSpanProcessor(memory))
    tracer = provider.get_tracer("data-service")

    with tracer.start_as_current_span("SELECT audit_events") as span:
        span.set_attribute("db.system", "postgresql")
        span.set_attribute("db.name", "orders_db")
        span.set_attribute("db.operation", "SELECT orders_db")
        span.set_attribute("db.statement", "SELECT 1")
        span.set_attribute("db.user", "postgres")
        span.set_attribute("net.peer.name", "db.internal")
        span.set_attribute("net.peer.port", 5432)
    with tracer.start_as_current_span("noop"):
        pass

    finished = memory.get_finished_spans()
    provider.shutdown()
    database_span = next(span for span in finished if span.name == "SELECT audit_events")
    attributes = dict(database_span.attributes or {})
    assert attributes["db.system.name"] == "postgresql"
    assert attributes["db.namespace"] == "orders_db"
    assert attributes["db.operation.name"] == "SELECT"
    assert attributes["server.address"] == "db.internal"
    assert attributes["server.port"] == 5432
    assert "db.statement" not in attributes
    assert "db.query.text" not in attributes
    assert "db.user" not in attributes
    plain = next(span for span in finished if span.name == "noop")
    assert "db.system.name" not in dict(plain.attributes or {})


def test_metric_names_and_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    created: dict[str, dict[str, object]] = {}
    recorded: dict[str, list[dict[str, object]]] = {}

    class _Counter:
        def __init__(self, name: str) -> None:
            self._name = name

        def add(self, amount: int, attributes: dict[str, object] | None = None) -> None:
            del amount
            recorded.setdefault(self._name, []).append(dict(attributes or {}))

    class _Histogram:
        def __init__(self, name: str) -> None:
            self._name = name

        def record(self, amount: float, attributes: dict[str, object] | None = None) -> None:
            del amount
            recorded.setdefault(self._name, []).append(dict(attributes or {}))

    class _Meter:
        def create_counter(self, name: str, **kwargs: object) -> _Counter:
            created[name] = kwargs
            return _Counter(name)

        def create_histogram(self, name: str, **kwargs: object) -> _Histogram:
            created[name] = kwargs
            return _Histogram(name)

    monkeypatch.setattr("app.core.metrics.metrics.get_meter", lambda _name: _Meter())
    reset_instruments()
    try:
        with track_request("replicate") as status:
            status["result"] = "success"
        record_database_operation("gcp", "insert", "success")
        record_database_operation("aws", "select", "error")
        record_replication_failure("aws")
        record_chaos_injection()
    finally:
        reset_instruments()

    assert created["app.data_service.request.duration"]["unit"] == "s"
    assert set(created) == {
        "app.data_service.requests",
        "app.data_service.request.duration",
        "app.data_service.database.operations",
        "app.data_service.replication.failures",
        "app.data_service.chaos.injections",
    }
    assert recorded["app.data_service.requests"] == [{"operation": "replicate", "result": "success"}]
    assert recorded["app.data_service.database.operations"] == [
        {"cloud": "gcp", "operation": "insert", "result": "success"},
        {"cloud": "aws", "operation": "select", "result": "error"},
    ]
    assert recorded["app.data_service.replication.failures"] == [{"cloud": "aws"}]
    assert recorded["app.data_service.chaos.injections"] == [{"operation": "replicate"}]
    assert "trace_id" not in str(recorded)


async def test_incoming_trace_continues_and_chaos_log_keeps_trace_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", lambda **_kwargs: _MetricExporter())
    monkeypatch.setattr(telemetry, "OTLPLogExporter", lambda **_kwargs: _LogExporter())
    monkeypatch.setattr(telemetry, "_setup_process_metrics", lambda: None)
    previous_configured = telemetry._configured
    telemetry._configured = False
    memory = InMemorySpanExporter()
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda **_kwargs: memory)
    monkeypatch.setattr(telemetry, "BatchSpanProcessor", lambda exporter: SimpleSpanProcessor(exporter))
    previous_provider = trace._TRACER_PROVIDER
    previous_once = trace._TRACER_PROVIDER_SET_ONCE
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    gcp = FakeAuditStore("gcp")
    aws = FakeAuditStore("aws")
    captured: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            captured.append(JsonFormatter("data-service").format(record))

    try:
        application = create_app(
            settings=build_settings(),
            gcp_database=gcp,
            aws_database=aws,
            clock=Clock(),
        )
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
            logging.getLogger().addHandler(_Capture())
            replicated = await client.post(
                "/api/v1/data/replicate",
                json=EVENT,
                headers={"X-Request-ID": REQUEST_ID, "traceparent": INCOMING_TRACEPARENT},
            )
            configured = await client.post(
                "/internal/chaos",
                json={"error_rate": 1, "delay_ms": 0, "duration_seconds": 30},
                headers={"X-Chaos-Token": TOKEN, "traceparent": INCOMING_TRACEPARENT},
            )
            failed = await client.post(
                "/api/v1/data/replicate",
                json=EVENT,
                headers={"X-Request-ID": REQUEST_ID, "traceparent": INCOMING_TRACEPARENT},
            )
    finally:
        telemetry.shutdown_telemetry()
        telemetry._configured = previous_configured
        trace._TRACER_PROVIDER = previous_provider
        trace._TRACER_PROVIDER_SET_ONCE = previous_once

    assert replicated.status_code == 201
    assert configured.status_code == 200
    assert failed.status_code == 503
    server_spans = [span for span in memory.get_finished_spans() if span.kind == SpanKind.SERVER]
    replicate_spans = [span for span in server_spans if span.name == "POST /api/v1/data/replicate"]
    assert replicate_spans
    assert all(format(span.context.trace_id, "032x") == INCOMING_TRACE_ID for span in replicate_spans)
    assert all(
        span.parent is not None and format(span.parent.span_id, "016x") == INCOMING_SPAN_ID
        for span in replicate_spans
    )
    assert replicate_spans[0].resource.attributes["service.name"] == "data-service"
    chaos_logs = [line for line in captured if "chaos.injected_error" in line]
    assert chaos_logs
    assert f'"trace_id":"{INCOMING_TRACE_ID}"' in chaos_logs[-1]
    assert TOKEN not in chaos_logs[-1]
    assert "://" not in chaos_logs[-1]
