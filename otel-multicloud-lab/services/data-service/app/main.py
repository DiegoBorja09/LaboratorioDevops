from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
from sqlalchemy.ext.asyncio import AsyncEngine

from app.api.router import api_router
from app.core.chaos import ChaosController
from app.core.config import Settings, get_settings
from app.core.exceptions import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import RequestContextMiddleware
from app.core.telemetry import sdk_disabled, setup_telemetry, shutdown_telemetry
from app.database.session import create_db_engine, create_session_factory
from app.services.audit_store import AuditStore, SqlAuditStore, UnavailableAuditStore
from app.services.replication_service import ReplicationService

_httpx_instrumented = False
_sqlalchemy_instrumented = False


def _instrument_httpx() -> None:
    global _httpx_instrumented
    if sdk_disabled() or _httpx_instrumented:
        return
    HTTPXClientInstrumentor().instrument()
    _httpx_instrumented = True


def _instrument_sqlalchemy(engines: list[AsyncEngine]) -> None:
    global _sqlalchemy_instrumented
    if sdk_disabled() or _sqlalchemy_instrumented or not engines:
        return
    SQLAlchemyInstrumentor().instrument(
        engines=[engine.sync_engine for engine in engines],
        enable_commenter=False,
        enable_attribute_commenter=False,
    )
    _sqlalchemy_instrumented = True


def _instrument_fastapi(app: FastAPI) -> None:
    if sdk_disabled() or getattr(app.state, "otel_instrumented", False):
        return
    FastAPIInstrumentor.instrument_app(
        app,
        excluded_urls="/health",
        exclude_spans=["receive", "send"],
    )
    app.state.otel_instrumented = True


def _build_store(
    cloud: str,
    url: str,
    injected: AuditStore | None,
    engines: list[AsyncEngine],
) -> AuditStore:
    if injected is not None:
        return injected
    if not url:
        return UnavailableAuditStore(cloud)
    engine = create_db_engine(url)
    engines.append(engine)
    return SqlAuditStore(cloud, create_session_factory(engine))


def create_app(
    settings: Settings | None = None,
    gcp_database: AuditStore | None = None,
    aws_database: AuditStore | None = None,
    clock: Callable[[], float] | None = None,
    random_source: Callable[[], float] | None = None,
) -> FastAPI:
    resolved = settings or get_settings()
    configure_logging(resolved.service_name, resolved.log_level)
    engines: list[AsyncEngine] = []
    gcp = _build_store("gcp", resolved.gcp_database_url, gcp_database, engines)
    aws = _build_store("aws", resolved.aws_database_url, aws_database, engines)
    chaos = ChaosController(resolved, clock=clock, random_source=random_source)
    replication = ReplicationService(gcp, aws, chaos)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        configure_logging(resolved.service_name, resolved.log_level)
        yield
        for engine in engines:
            await engine.dispose()
        shutdown_telemetry()

    app = FastAPI(
        title="data-service",
        version="0.1.0",
        debug=False,
        redirect_slashes=False,
        lifespan=lifespan,
    )
    app.state.settings = resolved
    app.state.engines = engines
    app.state.chaos = chaos
    app.state.replication_service = replication
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(api_router)
    setup_telemetry()
    _instrument_httpx()
    _instrument_sqlalchemy(engines)
    _instrument_fastapi(app)
    return app


app = create_app()
