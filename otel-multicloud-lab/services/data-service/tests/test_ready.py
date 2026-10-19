from tests.conftest import Lab


async def test_ready_when_both_databases_respond(lab: Lab) -> None:
    response = await lab.client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "databases": {"gcp": "connected", "aws": "connected"},
    }
    assert lab.gcp.pings == 1
    assert lab.aws.pings == 1
    assert "://" not in response.text


async def test_ready_when_one_database_fails(lab: Lab) -> None:
    lab.aws.fail = True

    response = await lab.client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {
        "status": "unavailable",
        "databases": {"gcp": "connected", "aws": "unavailable"},
    }
    assert lab.gcp.pings == 1
    assert lab.aws.pings == 1
    assert "password" not in response.text.lower()
