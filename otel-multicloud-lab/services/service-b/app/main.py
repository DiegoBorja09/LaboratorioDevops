from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.telemetry import sdk_disabled, setup_telemetry, shutdown_telemetry
from app.database.session import create_db_engine, create_session_factory

_instrumented_engines: set[int] = set()


def _instrument_sqlalchemy(engine: AsyncEngine) -> None:
    engine_id = id(engine)
    if sdk_disabled() or engine_id in _instrumented_engines:
        return
    SQLAlchemyInstrumentor().instrument(
        engine=engine.sync_engine,
        enable_commenter=False,
        enable_attribute_commenter=False,
    )
    _instrumented_engines.add(engine_id)


def _instrument_fastapi(app: FastAPI) -> None:
    if sdk_disabled() or getattr(app.state, "otel_instrumented", False):
        return
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/health",
        exclude_spans=["receive", "send"],
    )
    app.state.otel_instrumented = True


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.service_name, resolved_settings.log_level)
    engine = create_db_engine(resolved_settings.database_url)
    session_factory = create_session_factory(engine)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        configure_logging(resolved_settings.service_name, resolved_settings.log_level)
        yield
        await engine.dispose()
        shutdown_telemetry()

    app = FastAPI(
        title="service-b",
        version="0.1.0",
        debug=False,
        redirect_slashes=False,
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.engine = engine
    app.state.session_factory = session_factory
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)
    setup_telemetry()
    _instrument_sqlalchemy(engine)
    _instrument_fastapi(app)
    return app


app = create_app()
