import json
from decimal import Decimal

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app

REQUEST_ID = "11111111-1111-1111-1111-111111111111"
ORDER = {
    "customer_id": "customer-001",
    "amount": 150000.50,
    "currency": "cop",
}


def _processed_body(request: httpx.Request) -> bytes:
    payload = json.loads(request.content.decode("utf-8"), parse_float=Decimal)
    amount = format(payload["amount"], "f")
    return (
        "{"
        '"id":"22222222-2222-2222-2222-222222222222",'
        '"customer_id":"customer-001",'
        f'"amount":{amount},'
        f'"currency":"{payload["currency"]}",'
        '"status":"PROCESSED",'
        '"created_at":"2026-01-01T00:00:00+00:00"'
        "}"
    ).encode("utf-8")


async def test_amount_must_be_greater_than_zero(build_client) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        return httpx.Response(201)

    client = await build_client(handler)
    response = await client.post(
        "/api/v1/orders",
        json={"customer_id": "customer-001", "amount": 0, "currency": "COP"},
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["request_id"] == REQUEST_ID
    assert "amount" in body["error"]["message"]
    assert calls["count"] == 0


async def test_currency_is_uppercased(build_client) -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = request.content
        captured["request_id"] = request.headers["X-Request-ID"]
        captured["url"] = str(request.url)
        return httpx.Response(
            201,
            content=_processed_body(request),
            headers={"content-type": "application/json"},
        )

    client = await build_client(handler)
    response = await client.post(
        "/api/v1/orders",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )

    outbound = json.loads(captured["body"], parse_float=Decimal)
    assert str(captured["url"]).endswith("/api/v1/orders/process")
    assert captured["request_id"] == REQUEST_ID
    assert outbound["currency"] == "COP"
    assert outbound["amount"] == Decimal("150000.50")
    assert b'"amount":150000.50' in captured["body"]
    assert response.status_code == 201
    assert response.json()["currency"] == "COP"


async def test_create_order_when_service_b_succeeds(build_client) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        assert request.method == "POST"
        assert request.headers["X-Request-ID"] == REQUEST_ID
        return httpx.Response(
            201,
            content=_processed_body(request),
            headers={"content-type": "application/json"},
        )

    client = await build_client(handler)
    response = await client.post(
        "/api/v1/orders",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert calls["count"] == 1
    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == REQUEST_ID
    body = response.json()
    assert body["id"] == "22222222-2222-2222-2222-222222222222"
    assert body["customer_id"] == "customer-001"
    assert body["status"] == "PROCESSED"
    assert body["currency"] == "COP"


async def test_returns_502_when_service_b_is_unavailable(build_client) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ConnectError("All connection attempts failed")

    client = await build_client(handler)
    response = await client.post(
        "/api/v1/orders",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert calls["count"] == 1
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "SERVICE_B_UNAVAILABLE"
    assert body["error"]["message"] == "No fue posible comunicarse con service-b"
    assert body["error"]["request_id"] == REQUEST_ID
    assert "traceback" not in response.text.lower()
    assert "postgres" not in response.text.lower()


async def test_returns_504_when_service_b_times_out(build_client) -> None:
    calls = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["count"] += 1
        raise httpx.ReadTimeout("timed out", request=request)

    client = await build_client(handler)
    response = await client.post(
        "/api/v1/orders",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert calls["count"] == 1
    assert response.status_code == 504
    body = response.json()
    assert body["error"]["code"] == "SERVICE_B_TIMEOUT"
    assert body["error"]["request_id"] == REQUEST_ID


@pytest.mark.parametrize("amount", [-1, 0])
async def test_rejected_amounts_do_not_call_service_b(build_client, amount: int) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("service-b no debe recibir una orden inválida")

    client = await build_client(handler)
    response = await client.post(
        "/api/v1/orders",
        json={"customer_id": "customer-001", "amount": amount, "currency": "COP"},
    )

    assert response.status_code == 422


def _settings_with_data_service() -> Settings:
    return Settings(
        service_name="service-a",
        service_b_url="http://service-b:8080",
        service_b_timeout_seconds=5,
        data_service_url="http://data-service:8080",
        log_level="INFO",
    )


async def test_successful_order_replicates_the_audit_event() -> None:
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/replicate"):
            return httpx.Response(201, json={"status": "replicated"})
        return httpx.Response(
            201,
            content=_processed_body(request),
            headers={"content-type": "application/json"},
        )

    application = create_app(settings=_settings_with_data_service(), transport=httpx.MockTransport(handler))
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/api/v1/orders", json=ORDER, headers={"X-Request-ID": REQUEST_ID})
    await application.state.http_client.aclose()

    assert response.status_code == 201
    assert response.json()["id"] == "22222222-2222-2222-2222-222222222222"
    assert [request.url.path for request in calls] == ["/api/v1/orders/process", "/api/v1/data/replicate"]
    replicated = json.loads(calls[1].content)
    assert replicated["order_id"] == "22222222-2222-2222-2222-222222222222"
    assert replicated["source_service"] == "service-a"
    assert replicated["status"] == "created"
    assert replicated["event_id"]
    assert calls[1].headers["X-Request-ID"] == REQUEST_ID


async def test_data_service_failure_does_not_create_another_order() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path.endswith("/replicate"):
            return httpx.Response(503, json={"error": {"code": "REPLICATION_FAILED"}})
        return httpx.Response(
            201,
            content=_processed_body(request),
            headers={"content-type": "application/json"},
        )

    application = create_app(settings=_settings_with_data_service(), transport=httpx.MockTransport(handler))
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/api/v1/orders", json=ORDER, headers={"X-Request-ID": REQUEST_ID})
    await application.state.http_client.aclose()

    assert calls == ["/api/v1/orders/process", "/api/v1/data/replicate"]
    assert response.status_code == 502
    body = response.json()
    assert body["error"]["code"] == "DATA_SERVICE_UNAVAILABLE"
    assert body["error"]["request_id"] == REQUEST_ID
    assert "service-b" in body["error"]["message"]
