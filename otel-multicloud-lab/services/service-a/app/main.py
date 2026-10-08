from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

import httpx
from fastapi import FastAPI

from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.telemetry import sdk_disabled, setup_telemetry, shutdown_telemetry
from app.services.order_service import OrderService

_httpx_instrumented = False


def _instrument_clients() -> None:
    global _httpx_instrumented
    if sdk_disabled() or _httpx_instrumented:
        return
    HTTPXClientInstrumentor().instrument()
    _httpx_instrumented = True


def _instrument_fastapi(app: FastAPI) -> None:
    if sdk_disabled() or getattr(app.state, "otel_instrumented", False):
        return
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/health",
        exclude_spans=["receive", "send"],
    )
    app.state.otel_instrumented = True


def create_app(
    settings: Settings | None = None,
    transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.service_name, resolved_settings.log_level)
    http_client = httpx.AsyncClient(
        transport=transport,
        follow_redirects=False,
        trust_env=False,
    )

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved_settings.service_name, resolved_settings.log_level)
        yield
        await http_client.aclose()
        shutdown_telemetry()

    app = FastAPI(
        title="service-a",
        version="0.1.0",
        debug=False,
        redirect_slashes=False,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.http_client = http_client
    app.state.order_service = OrderService(http_client, resolved_settings)
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)
    setup_telemetry()
    _instrument_clients()
    _instrument_fastapi(app)
    return app


app = create_app()
