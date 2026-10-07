import json
import logging

import httpx

from app.core.logging import JsonFormatter


def test_json_formatter_includes_request_fields() -> None:
    formatter = JsonFormatter("service-a")
    record = logging.LogRecord(
        name="app.access",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg="Solicitud procesada",
        args=(),
        exc_info=None,
    )
    record.request_id = "11111111-1111-1111-1111-111111111111"
    record.method = "POST"
    record.path = "/api/v1/orders"
    record.status_code = 201
    record.duration_ms = 12

    payload = json.loads(formatter.format(record))

    assert payload["service"] == "service-a"
    assert payload["level"] == "INFO"
    assert payload["message"] == "Solicitud procesada"
    assert payload["request_id"] == "11111111-1111-1111-1111-111111111111"
    assert payload["method"] == "POST"
    assert payload["path"] == "/api/v1/orders"
    assert payload["status_code"] == 201
    assert payload["duration_ms"] == 12
    assert "trace_id" not in payload
    assert "span_id" not in payload
    assert "timestamp" in payload


async def test_health(build_client) -> None:
    client = await build_client(lambda request: httpx.Response(500))

    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "service-a"}
    assert response.headers["X-Request-ID"]
