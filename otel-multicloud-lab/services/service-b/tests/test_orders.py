from uuid import uuid4

import pytest

REQUEST_ID = "11111111-1111-1111-1111-111111111111"
ORDER = {
    "customer_id": "customer-001",
    "amount": 150000.50,
    "currency": "cop",
}


async def test_create_order(client) -> None:
    response = await client.post(
        "/api/v1/orders/process",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == REQUEST_ID
    body = response.json()
    assert body["customer_id"] == "customer-001"
    assert body["currency"] == "COP"
    assert body["status"] == "PROCESSED"
    assert body["amount"] == 150000.50
    assert "150000.50" in response.text
    assert body["created_at"]
    assert body["id"]


async def test_list_orders_is_empty(client) -> None:
    response = await client.get("/api/v1/orders")

    assert response.status_code == 200
    assert response.json() == []


async def test_list_orders_returns_created_orders(client) -> None:
    first = await client.post(
        "/api/v1/orders/process",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )
    second = await client.post(
        "/api/v1/orders/process",
        json={**ORDER, "customer_id": "customer-002"},
        headers={"X-Request-ID": "22222222-2222-2222-2222-222222222222"},
    )

    response = await client.get("/api/v1/orders")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {item["id"] for item in body} == {first.json()["id"], second.json()["id"]}
    assert {item["customer_id"] for item in body} == {"customer-001", "customer-002"}


async def test_get_existing_order(client) -> None:
    created = await client.post(
        "/api/v1/orders/process",
        json=ORDER,
        headers={"X-Request-ID": REQUEST_ID},
    )
    order_id = created.json()["id"]

    response = await client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 200
    body = response.json()
    assert body["id"] == order_id
    assert body["customer_id"] == "customer-001"
    assert body["currency"] == "COP"
    assert body["status"] == "PROCESSED"
    assert body["amount"] == 150000.50


async def test_get_missing_order_returns_404(client) -> None:
    missing_id = uuid4()
    response = await client.get(
        f"/api/v1/orders/{missing_id}",
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 404
    body = response.json()
    assert body["error"]["code"] == "ORDER_NOT_FOUND"
    assert body["error"]["request_id"] == REQUEST_ID
    assert "traceback" not in response.text.lower()


@pytest.mark.parametrize("order_id", ["not-a-uuid", "123", "order-001"])
async def test_invalid_uuid(client, order_id: str) -> None:
    response = await client.get(f"/api/v1/orders/{order_id}")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_UUID"
