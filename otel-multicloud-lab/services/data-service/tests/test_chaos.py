from app.core.config import Settings
from app.main import create_app
from tests.conftest import EVENT, REQUEST_ID, TOKEN, Lab, build_settings
from tests.fakes import Clock, FakeAuditStore


async def test_chaos_is_disabled_by_default(lab: Lab) -> None:
    assert lab.client is not None
    response = await lab.client.post("/api/v1/data/replicate", json=EVENT, headers={"X-Request-ID": REQUEST_ID})

    assert response.status_code == 201
    assert lab.gcp.inserts == 1
    assert lab.aws.inserts == 1


async def test_chaos_endpoint_rejects_a_missing_or_wrong_token(lab: Lab) -> None:
    missing = await lab.client.post(
        "/internal/chaos",
        json={"error_rate": 1, "delay_ms": 0, "duration_seconds": 30},
    )
    wrong = await lab.client.post(
        "/internal/chaos",
        json={"error_rate": 1, "delay_ms": 0, "duration_seconds": 30},
        headers={"X-Chaos-Token": "other-token"},
    )

    assert missing.status_code == 401
    assert wrong.status_code == 401
    assert missing.json()["error"]["code"] == "CHAOS_UNAUTHORIZED"
    assert TOKEN not in missing.text
    assert TOKEN not in wrong.text
    assert "other-token" not in wrong.text
    follow_up = await lab.client.post("/api/v1/data/replicate", json=EVENT, headers={"X-Request-ID": REQUEST_ID})
    assert follow_up.status_code == 201


async def test_chaos_endpoint_rejects_values_outside_the_allowed_range(lab: Lab) -> None:
    response = await lab.client.post(
        "/internal/chaos",
        json={"error_rate": 1.5, "delay_ms": 0, "duration_seconds": 601},
        headers={"X-Chaos-Token": TOKEN},
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"
    assert TOKEN not in response.text


async def test_chaos_injects_an_error_before_writing_and_then_expires(lab: Lab) -> None:
    configured = await lab.client.post(
        "/internal/chaos",
        json={"error_rate": 1, "delay_ms": 0, "duration_seconds": 30},
        headers={"X-Chaos-Token": TOKEN},
    )
    failed = await lab.client.post("/api/v1/data/replicate", json=EVENT, headers={"X-Request-ID": REQUEST_ID})

    assert configured.status_code == 200
    body = configured.json()
    assert body["enabled"] is True
    assert body["error_rate"] == 1
    assert body["delay_ms"] == 0
    assert TOKEN not in configured.text
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "CHAOS_INJECTED"
    assert lab.gcp.inserts == 0
    assert lab.aws.inserts == 0

    lab.clock.now = 30
    recovered = await lab.client.post("/api/v1/data/replicate", json=EVENT, headers={"X-Request-ID": REQUEST_ID})

    assert recovered.status_code == 201
    assert lab.gcp.inserts == 1
    assert lab.aws.inserts == 1


async def test_environment_chaos_can_fail_before_any_write() -> None:
    gcp = FakeAuditStore("gcp")
    aws = FakeAuditStore("aws")
    settings = build_settings(chaos_enabled=True, chaos_error_rate=1, chaos_delay_ms=0)
    application = create_app(settings=settings, gcp_database=gcp, aws_database=aws, clock=Clock())
    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post("/api/v1/data/replicate", json=EVENT, headers={"X-Request-ID": REQUEST_ID})

    assert isinstance(settings, Settings)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "CHAOS_INJECTED"
    assert gcp.inserts == 0
    assert aws.inserts == 0
