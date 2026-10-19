from tests.conftest import Lab


async def test_health_does_not_touch_databases(lab: Lab) -> None:
    response = await lab.client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "healthy", "service": "data-service"}
    assert lab.gcp.pings == 0
    assert lab.aws.pings == 0
    assert lab.gcp.inserts == 0
    assert lab.aws.inserts == 0
