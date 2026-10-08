import os

os.environ["OTEL_SDK_DISABLED"] = "true"

import inspect
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.database.base import Base
from app.main import create_app
from app.models.order import Order


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[AsyncClient]:
    database_path = tmp_path / "orders.db"
    settings = Settings(
        service_name="service-b",
        database_url=f"sqlite+aiosqlite:///{database_path.as_posix()}",
        log_level="INFO",
    )
    application = create_app(settings)
    _ = Order
    async with application.state.engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    transport_kwargs: dict[str, object] = {"app": application}
    if "lifespan" in inspect.signature(ASGITransport.__init__).parameters:
        transport_kwargs["lifespan"] = "off"

    async with AsyncClient(
        transport=ASGITransport(**transport_kwargs),
        base_url="http://test",
    ) as http_client:
        yield http_client

    await application.state.engine.dispose()
