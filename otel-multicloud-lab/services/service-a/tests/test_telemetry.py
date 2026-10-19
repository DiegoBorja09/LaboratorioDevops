import re
from decimal import Decimal

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.baggage.propagation import W3CBaggagePropagator
from opentelemetry.propagate import get_global_textmap
from opentelemetry.sdk.metrics.export import MetricExportResult
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator
from opentelemetry.util._once import Once

from app.core.config import Settings
from app.core.errors import AppError
from app.core.metrics import track_order_request
from app.core.telemetry import setup_telemetry
from app.main import create_app
from app.schemas.order import OrderCreate
from app.services.order_service import validate_order

import app.core.telemetry as telemetry
import app.main as main_module

REQUEST_ID = "11111111-1111-1111-1111-111111111111"
ORDER = {
    "customer_id": "customer-001",
    "amount": 150000.50,
    "currency": "cop",
}
INCOMING_TRACE_ID = "0123456789abcdef0123456789abcdef"
INCOMING_SPAN_ID = "0123456789abcdef"
INCOMING_TRACEPARENT = f"00-{INCOMING_TRACE_ID}-{INCOMING_SPAN_ID}-01"
_TRACEPARENT = re.compile(r"00-[0-9a-f]{32}-[0-9a-f]{16}-[0-9a-f]{2}$")


class _RecordingSpan:
    def __init__(self) -> None:
        self.attributes: dict[str, object] = {}
        self.exceptions: list[BaseException] = []
        self.status_code: StatusCode | None = None

    def set_attribute(self, key: str, value: object) -> None:
        self.attributes[key] = value

    def record_exception(self, exception: BaseException) -> None:
        self.exceptions.append(exception)

    def set_status(self, status: object) -> None:
        self.status_code = status.status_code

    def __enter__(self) -> "_RecordingSpan":
        return self

    def __exit__(self, *_args: object) -> bool:
        return False


class _RecordingTracer:
    def __init__(self, span: _RecordingSpan) -> None:
        self._span = span
        self.name: str | None = None

    def start_as_current_span(self, name: str, *_args: object, **_kwargs: object) -> _RecordingSpan:
        self.name = name
        return self._span


def test_app_starts_when_sdk_is_disabled(build_client) -> None:
    assert telemetry.sdk_disabled() is True
    client_factory = build_client
    assert client_factory is not None


def test_disabled_sdk_does_not_initialize_providers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")
    telemetry._configured = False
    called: list[str] = []
    monkeypatch.setattr(telemetry, "_setup_traces", lambda _resource: called.append("traces"))
    monkeypatch.setattr(telemetry, "_setup_metrics", lambda _resource: called.append("metrics"))
    monkeypatch.setattr(telemetry, "_setup_logs", lambda _resource: called.append("logs"))
    monkeypatch.setattr(telemetry, "_setup_process_metrics", lambda: called.append("process"))

    setup_telemetry()

    assert called == []
    assert telemetry._configured is False


async def test_health_still_works_with_telemetry_disabled(build_client) -> None:
    client = await build_client(lambda request: httpx.Response(500))

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "service-a"}


async def test_create_order_keeps_request_id_when_telemetry_is_disabled(build_client) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request_id"] = request.headers.get("X-Request-ID")
        captured["body"] = request.content
        return httpx.Response(
            201,
            content=(
                b'{"id":"22222222-2222-2222-2222-222222222222",'
                b'"customer_id":"customer-001","amount":150000.50,'
                b'"currency":"COP","status":"PROCESSED",'
                b'"created_at":"2026-01-01T00:00:00+00:00"}'
            ),
            headers={"content-type": "application/json"},
        )

    client = await build_client(handler)
    response = await client.post(
        "/api/v1/orders",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == REQUEST_ID
    assert captured["request_id"] == REQUEST_ID
    assert b'"currency":"COP"' in captured["body"]


def test_validate_order_span_does_not_expose_sensitive_data(monkeypatch: pytest.MonkeyPatch) -> None:
    span = _RecordingSpan()
    tracer = _RecordingTracer(span)
    monkeypatch.setattr(
        "app.services.order_service.trace.get_tracer",
        lambda *_args, **_kwargs: tracer,
    )
    order = OrderCreate(customer_id="customer-001", amount=Decimal("150000.50"), currency="cop")

    validated = validate_order(order)

    assert tracer.name == "validate_order"
    assert validated.currency == "COP"
    assert span.attributes == {
        "order.currency": "COP",
        "order.validation.result": "success",
    }
    rendered = " ".join(f"{key}={value}" for key, value in span.attributes.items())
    assert "customer-001" not in rendered
    assert "150000.50" not in rendered


def test_validate_order_span_records_validation_error(monkeypatch: pytest.MonkeyPatch) -> None:
    span = _RecordingSpan()
    tracer = _RecordingTracer(span)
    monkeypatch.setattr(
        "app.services.order_service.trace.get_tracer",
        lambda *_args, **_kwargs: tracer,
    )
    order = OrderCreate.model_construct(customer_id="", amount=Decimal("10"), currency="COP")

    with pytest.raises(AppError):
        validate_order(order)

    assert span.attributes["order.validation.result"] == "error"
    assert span.exceptions
    assert span.status_code == StatusCode.ERROR
    assert "customer_id" not in span.attributes


def test_setup_telemetry_configures_one_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    telemetry._configured = False
    calls: list[object] = []
    real_set_provider = trace.set_tracer_provider

    def spy(provider: object) -> None:
        calls.append(provider)
        real_set_provider(provider)

    class _Exporter:
        def export(self, spans: object) -> SpanExportResult:
            del spans
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            return None

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            del timeout_millis
            return True

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

    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", spy)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda **_kwargs: _Exporter())
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", lambda **_kwargs: _MetricExporter())
    monkeypatch.setattr(telemetry, "OTLPLogExporter", lambda **_kwargs: _LogExporter())

    try:
        setup_telemetry()
        first = trace.get_tracer_provider()
        setup_telemetry()
        second = trace.get_tracer_provider()
    finally:
        telemetry.shutdown_telemetry()

    assert len(calls) == 1
    assert first is second
    assert isinstance(first, TracerProvider)


def test_health_is_excluded_when_instrumentation_is_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    previous = telemetry._configured
    telemetry._configured = True
    captured: dict[str, object] = {}

    def fake_instrument_app(app: object, excluded_urls: str | None = None, **_kwargs: object) -> None:
        del app
        captured["excluded_urls"] = excluded_urls

    monkeypatch.setattr(
        "app.main.FastAPIInstrumentor.instrument_app",
        staticmethod(fake_instrument_app),
    )
    monkeypatch.setattr(main_module, "_httpx_instrumented", True)

    try:
        create_app()
    finally:
        telemetry._configured = previous

    assert captured["excluded_urls"] == "/health"


def test_collector_export_failure_does_not_break_validation(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    class _FailingExporter:
        def export(self, spans: object) -> SpanExportResult:
            del spans
            raise ConnectionError("collector no disponible")

        def shutdown(self) -> None:
            return None

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_FailingExporter()))
    tracer = provider.get_tracer("service-a")
    order = OrderCreate(customer_id="customer-001", amount=Decimal("10.00"), currency="COP")

    with tracer.start_as_current_span("request"):
        validated = validate_order(order)

    assert validated.currency == "COP"
    provider.shutdown()


def test_order_metrics_record_error_and_release_in_flight(monkeypatch: pytest.MonkeyPatch) -> None:
    recorded: dict[str, list[tuple[object, dict[str, object]]]] = {
        "requests": [],
        "errors": [],
        "duration": [],
        "in_flight": [],
    }

    class _Counter:
        def __init__(self, name: str) -> None:
            self._name = name

        def add(self, amount: int, attributes: dict[str, object] | None = None) -> None:
            recorded[self._name].append((amount, dict(attributes or {})))

    class _Histogram:
        def record(self, amount: float, attributes: dict[str, object] | None = None) -> None:
            recorded["duration"].append((amount, dict(attributes or {})))

    monkeypatch.setattr(
        "app.core.metrics._instruments",
        lambda: (_Counter("requests"), _Counter("errors"), _Histogram(), _Counter("in_flight")),
    )

    with pytest.raises(AppError):
        with track_order_request() as status:
            status["code"] = 422
            raise AppError("VALIDATION_ERROR", "currency debe tener exactamente tres caracteres", 422)

    assert [call[0] for call in recorded["in_flight"]] == [1, -1]
    assert recorded["in_flight"][0][1] == recorded["in_flight"][1][1]
    assert recorded["requests"][0][1]["result"] == "error"
    assert recorded["requests"][0][1]["http.response.status_code"] == 422
    assert recorded["errors"][0][1]["http.route"] == "/api/v1/orders"
    assert recorded["duration"]
    rendered = str(recorded)
    assert "customer-001" not in rendered
    assert "trace_id" not in rendered


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


async def test_outbound_call_propagates_incoming_traceparent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    monkeypatch.setattr(telemetry, "OTLPMetricExporter", lambda **_kwargs: _MetricExporter())
    monkeypatch.setattr(telemetry, "OTLPLogExporter", lambda **_kwargs: _LogExporter())
    monkeypatch.setattr(telemetry, "_setup_process_metrics", lambda: None)
    previous_configured = telemetry._configured
    telemetry._configured = False
    memory = InMemorySpanExporter()
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda **_kwargs: memory)
    monkeypatch.setattr(
        telemetry,
        "BatchSpanProcessor",
        lambda exporter: SimpleSpanProcessor(exporter),
    )
    previous_provider = trace._TRACER_PROVIDER
    previous_once = trace._TRACER_PROVIDER_SET_ONCE
    trace._TRACER_PROVIDER = None
    trace._TRACER_PROVIDER_SET_ONCE = Once()
    captured: dict[str, str | None] = {}
    application = None
    finished: list[object] = []
    propagators: list[object] = []

    def handler(request: httpx.Request) -> httpx.Response:
        captured["traceparent"] = request.headers.get("traceparent")
        return httpx.Response(
            201,
            content=b'{"id":"22222222-2222-2222-2222-222222222222","status":"PROCESSED"}',
            headers={"content-type": "application/json"},
        )

    try:
        application = create_app(transport=httpx.MockTransport(handler))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/orders",
                json=ORDER,
                headers={
                    "X-Request-ID": REQUEST_ID,
                    "traceparent": INCOMING_TRACEPARENT,
                },
            )
        finished = list(memory.get_finished_spans())
        propagators = list(getattr(get_global_textmap(), "_propagators", ()))
    finally:
        if application is not None:
            await application.state.http_client.aclose()
        telemetry.shutdown_telemetry()
        telemetry._configured = previous_configured
        trace._TRACER_PROVIDER = previous_provider
        trace._TRACER_PROVIDER_SET_ONCE = previous_once

    assert response.status_code == 201
    traceparent = captured["traceparent"]
    assert traceparent is not None
    assert _TRACEPARENT.fullmatch(traceparent)
    _version, trace_id, span_id, _flags = traceparent.split("-")
    assert trace_id == INCOMING_TRACE_ID
    assert span_id != INCOMING_SPAN_ID

    spans = finished
    server_spans = [span for span in spans if span.kind == SpanKind.SERVER]
    client_spans = [span for span in spans if span.kind == SpanKind.CLIENT]
    assert len(server_spans) == 1
    assert len(client_spans) == 1
    server_span = server_spans[0]
    client_span = client_spans[0]
    assert format(server_span.context.trace_id, "032x") == INCOMING_TRACE_ID
    assert format(client_span.context.trace_id, "032x") == INCOMING_TRACE_ID
    assert format(client_span.context.span_id, "016x") == span_id
    assert server_span.parent is not None
    assert format(server_span.parent.span_id, "016x") == INCOMING_SPAN_ID
    assert client_span.parent is not None
    assert client_span.parent.span_id == server_span.context.span_id
    assert server_span.resource.attributes["service.name"] == "service-a"
    assert client_span.resource.attributes["service.name"] == "service-a"
    assert any(isinstance(item, TraceContextTextMapPropagator) for item in propagators)
    assert any(isinstance(item, W3CBaggagePropagator) for item in propagators)


async def test_data_service_call_continues_the_same_trace(monkeypatch: pytest.MonkeyPatch) -> None:
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
    captured: list[dict[str, str | None]] = []
    application = None

    def handler(request: httpx.Request) -> httpx.Response:
        captured.append(
            {
                "path": request.url.path,
                "traceparent": request.headers.get("traceparent"),
                "baggage": request.headers.get("baggage"),
                "request_id": request.headers.get("X-Request-ID"),
            }
        )
        if request.url.path.endswith("/replicate"):
            return httpx.Response(201, json={"status": "replicated"})
        return httpx.Response(
            201,
            content=b'{"id":"22222222-2222-2222-2222-222222222222","status":"PROCESSED"}',
            headers={"content-type": "application/json"},
        )

    settings = Settings(
        service_name="service-a",
        service_b_url="http://service-b:8080",
        service_b_timeout_seconds=5,
        data_service_url="http://data-service:8080",
        log_level="INFO",
    )
    try:
        application = create_app(settings=settings, transport=httpx.MockTransport(handler))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=application),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/v1/orders",
                json=ORDER,
                headers={
                    "X-Request-ID": REQUEST_ID,
                    "traceparent": INCOMING_TRACEPARENT,
                    "baggage": "lab=demo",
                },
            )
    finally:
        if application is not None:
            await application.state.http_client.aclose()
        telemetry.shutdown_telemetry()
        telemetry._configured = previous_configured
        trace._TRACER_PROVIDER = previous_provider
        trace._TRACER_PROVIDER_SET_ONCE = previous_once

    assert response.status_code == 201
    assert [item["path"] for item in captured] == ["/api/v1/orders/process", "/api/v1/data/replicate"]
    trace_ids = []
    for item in captured:
        assert item["request_id"] == REQUEST_ID
        assert item["traceparent"] is not None
        assert _TRACEPARENT.fullmatch(item["traceparent"])
        assert item["baggage"] is not None
        assert "lab=demo" in item["baggage"]
        trace_ids.append(item["traceparent"].split("-")[1])
    assert trace_ids == [INCOMING_TRACE_ID, INCOMING_TRACE_ID]
    client_spans = [span for span in memory.get_finished_spans() if span.kind == SpanKind.CLIENT]
    assert len(client_spans) == 2
    assert all(format(span.context.trace_id, "032x") == INCOMING_TRACE_ID for span in client_spans)
    assert all(span.resource.attributes["service.name"] == "service-a" for span in client_spans)
