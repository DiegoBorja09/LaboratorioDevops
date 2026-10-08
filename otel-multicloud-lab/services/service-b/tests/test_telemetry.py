from decimal import Decimal
from uuid import UUID

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult
from opentelemetry.trace import StatusCode
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.main import create_app
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreate
from app.services.order_service import process_order

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


class _Repository:
    async def add(self, order: object) -> object:
        return order


class _FailingRepository:
    async def add(self, order: object) -> object:
        del order
        raise SQLAlchemyError("db")


def _order() -> OrderCreate:
    return OrderCreate(customer_id="customer-001", amount=Decimal("150000.50"), currency="cop")


def _sqlite_settings(tmp_path) -> Settings:
    database_path = tmp_path / "telemetry.db"
    return Settings(
        service_name="service-b",
        database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
        log_level="INFO",
    )


def test_app_starts_when_sdk_is_disabled() -> None:
    assert telemetry.sdk_disabled() is True
    application = create_app(
        Settings(
            service_name="service-b",
            database_url="sqlite+aiosqlite:///:memory:",
            log_level="INFO",
        )
    )
    assert application.title == "service-b"
    application.state.engine.sync_engine.dispose()


async def test_health_still_works_with_telemetry_disabled(client) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "service-b",
        "database": "connected",
    }


async def test_process_order_keeps_response_when_telemetry_is_disabled(client) -> None:
    response = await client.post(
        "/api/v1/orders/process",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == REQUEST_ID
    body = response.json()
    assert body["currency"] == "COP"
    assert body["status"] == "PROCESSED"
    assert body["customer_id"] == "customer-001"
    assert body["amount"] == 150000.50


async def test_get_order_still_works_when_telemetry_is_disabled(client) -> None:
    created = await client.post(
        "/api/v1/orders/process",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )
    order_id = created.json()["id"]

    response = await client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 200
    assert response.json()["id"] == order_id
    assert response.json()["status"] == "PROCESSED"


async def test_process_order_span_does_not_expose_sensitive_data(monkeypatch: pytest.MonkeyPatch) -> None:
    span = _RecordingSpan()
    tracer = _RecordingTracer(span)
    monkeypatch.setattr(
        "app.services.order_service.trace.get_tracer",
        lambda *_args, **_kwargs: tracer,
    )

    saved = await process_order(_order(), UUID(REQUEST_ID), _Repository())

    assert tracer.name == "process_order"
    assert saved.currency == "COP"
    assert span.attributes == {
        "order.currency": "COP",
        "order.processing.result": "success",
        "order.status": "PROCESSED",
    }
    rendered = " ".join(f"{key}={value}" for key, value in span.attributes.items())
    assert "customer-001" not in rendered
    assert "150000.50" not in rendered
    assert "postgres" not in rendered.lower()


async def test_process_order_span_records_database_error(monkeypatch: pytest.MonkeyPatch) -> None:
    span = _RecordingSpan()
    tracer = _RecordingTracer(span)
    monkeypatch.setattr(
        "app.services.order_service.trace.get_tracer",
        lambda *_args, **_kwargs: tracer,
    )

    with pytest.raises(SQLAlchemyError):
        await process_order(_order(), UUID(REQUEST_ID), _FailingRepository())

    assert span.attributes["order.processing.result"] == "error"
    assert span.exceptions
    assert span.status_code == StatusCode.ERROR
    assert "customer_id" not in span.attributes
    assert "amount" not in span.attributes


def test_sqlalchemy_is_instrumented_once_on_the_existing_engine(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")
    previous = telemetry._configured
    telemetry._configured = True
    calls: list[dict[str, object]] = []
    created: list[object] = []
    real_create = main_module.create_db_engine

    class _Instrumentor:
        def instrument(self, **kwargs: object) -> None:
            calls.append(kwargs)

    def spy(database_url: str):
        engine = real_create(database_url)
        created.append(engine)
        return engine

    monkeypatch.setattr(main_module, "SQLAlchemyInstrumentor", _Instrumentor)
    monkeypatch.setattr(main_module, "create_db_engine", spy)
    monkeypatch.setattr(main_module, "_instrument_fastapi", lambda _app: None)
    application = None
    try:
        application = create_app(_sqlite_settings(tmp_path))
        main_module._instrument_sqlalchemy(application.state.engine)
    finally:
        telemetry._configured = previous
        if application is not None:
            application.state.engine.sync_engine.dispose()

    assert len(created) == 1
    assert created[0] is application.state.engine
    assert len(calls) == 1
    assert calls[0]["engine"] is application.state.engine.sync_engine
    assert calls[0]["enable_commenter"] is False
    assert calls[0]["enable_attribute_commenter"] is False
    assert calls[0].get("capture_parameters") is not True


def test_health_is_excluded_when_instrumentation_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
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
    monkeypatch.setattr(main_module, "_instrument_sqlalchemy", lambda _engine: None)
    application = None
    try:
        application = create_app(_sqlite_settings(tmp_path))
    finally:
        telemetry._configured = previous
        if application is not None:
            application.state.engine.sync_engine.dispose()

    assert captured["excluded_urls"] == "/health"


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

    setup_from = telemetry.setup_telemetry
    setup_from()
    first = trace.get_tracer_provider()
    setup_from()
    second = trace.get_tracer_provider()

    assert len(calls) == 1
    assert first is second
    assert isinstance(first, TracerProvider)


async def test_collector_export_failure_does_not_break_processing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OTEL_SDK_DISABLED", "false")

    class _FailingExporter:
        def export(self, spans: object) -> SpanExportResult:
            del spans
            raise ConnectionError("collector no disponible")

        def shutdown(self) -> None:
            return None

    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(_FailingExporter()))
    monkeypatch.setattr(
        "app.services.order_service.trace.get_tracer",
        lambda *_args, **_kwargs: provider.get_tracer("service-b"),
    )

    saved = await process_order(_order(), UUID(REQUEST_ID), _Repository())

    assert saved.currency == "COP"
    assert saved.status == "PROCESSED"
    provider.shutdown()


async def test_database_error_keeps_existing_http_response(client, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(self: OrderRepository, order: object) -> object:
        del self, order
        raise SQLAlchemyError("db")

    monkeypatch.setattr(OrderRepository, "add", fail)
    response = await client.post(
        "/api/v1/orders/process",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 500
    body = response.json()
    assert body["error"]["code"] == "INTERNAL_ERROR"
    assert body["error"]["message"] == "No fue posible completar la operación"
    assert body["error"]["request_id"] == REQUEST_ID
    lowered = response.text.lower()
    assert "traceback" not in lowered
    assert "customer-001" not in response.text
    assert "postgres://" not in lowered
    assert "150000.50" not in response.text
