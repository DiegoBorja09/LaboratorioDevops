from decimal import Decimal

import httpx
import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.trace import StatusCode

from app.core.errors import AppError
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

    monkeypatch.setattr(telemetry.trace, "set_tracer_provider", spy)
    monkeypatch.setattr(telemetry, "OTLPSpanExporter", lambda **_kwargs: _Exporter())

    setup_telemetry()
    first = trace.get_tracer_provider()
    setup_telemetry()
    second = trace.get_tracer_provider()

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
