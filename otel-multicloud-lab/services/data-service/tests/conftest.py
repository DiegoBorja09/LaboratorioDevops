import os

os.environ["OTEL_SDK_DISABLED"] = "true"

import inspect
from collections.abc import AsyncIterator
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from tests.fakes import Clock, FakeAuditStore

TOKEN = "lab-token"
REQUEST_ID = "11111111-1111-1111-1111-111111111111"
EVENT_ID = "33333333-3333-3333-3333-333333333333"
ORDER_ID = "22222222-2222-2222-2222-222222222222"
EVENT = {
    "event_id": EVENT_ID,
    "order_id": ORDER_ID,
    "source_service": "service-a",
    "status": "created",
}


@dataclass
class Lab:
    client: AsyncClient
    gcp: FakeAuditStore
    aws: FakeAuditStore
    clock: Clock


def build_settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "service_name": "data-service",
        "gcp_database_url": "",
        "aws_database_url": "",
        "log_level": "WARNING",
        "chaos_enabled": False,
        "chaos_error_rate": 0,
        "chaos_delay_ms": 0,
        "chaos_token": TOKEN,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
async def lab() -> AsyncIterator[Lab]:
    gcp = FakeAuditStore("gcp")
    aws = FakeAuditStore("aws")
    clock = Clock()
    application = create_app(
        settings=build_settings(),
        gcp_database=gcp,
        aws_database=aws,
        clock=clock,
    )
    transport_kwargs: dict[str, object] = {"app": application}
    if "lifespan" in inspect.signature(ASGITransport.__init__).parameters:
        transport_kwargs["lifespan"] = "off"
    async with AsyncClient(transport=ASGITransport(**transport_kwargs), base_url="http://test") as client:
        yield Lab(client=client, gcp=gcp, aws=aws, clock=clock)
