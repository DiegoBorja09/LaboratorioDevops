import json
from decimal import Decimal

import httpx
import pytest

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
