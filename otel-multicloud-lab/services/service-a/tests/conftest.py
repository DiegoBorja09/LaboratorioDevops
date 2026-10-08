import os

os.environ["OTEL_SDK_DISABLED"] = "true"

from collections.abc import AsyncIterator, Callable

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

Handler = Callable[[httpx.Request], httpx.Response]


@pytest.fixture
def settings() -> Settings:
    return Settings(
        service_name="service-a",
        service_b_url="http://service-b:8080",
        service_b_timeout_seconds=5,
        log_level="INFO",
    )


@pytest.fixture
async def build_client(settings: Settings) -> AsyncIterator[Callable[[Handler], AsyncClient]]:
    clients: list[httpx.AsyncClient] = []
    apps = []

    async def _build(handler: Handler) -> AsyncClient:
        transport = httpx.MockTransport(handler)
        app = create_app(settings=settings, transport=transport)
        apps.append(app)
        client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
        clients.append(client)
        return client

    yield _build

    for client in clients:
        await client.aclose()
    for app in apps:
        await app.state.http_client.aclose()
