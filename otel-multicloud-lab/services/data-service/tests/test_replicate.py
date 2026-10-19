from tests.conftest import EVENT, EVENT_ID, ORDER_ID, REQUEST_ID, Lab


async def test_replicate_writes_both_databases(lab: Lab) -> None:
    response = await lab.client.post(
        "/api/v1/data/replicate",
        json=EVENT,
        headers={"X-Request-ID": REQUEST_ID},
    )

    assert response.status_code == 201
    assert response.headers["X-Request-ID"] == REQUEST_ID
    assert response.json() == {
        "event_id": EVENT_ID,
        "order_id": ORDER_ID,
        "status": "replicated",
        "gcp": "stored",
        "aws": "stored",
    }
    assert lab.gcp.inserts == 1
    assert lab.aws.inserts == 1
    stored = next(iter(lab.gcp.records.values()))
    assert str(stored.event_id) == EVENT_ID
    assert str(stored.order_id) == ORDER_ID
    assert stored.source_service == "service-a"
    assert stored.status == "created"


async def test_replicate_is_idempotent_for_the_same_event_id(lab: Lab) -> None:
    first = await lab.client.post("/api/v1/data/replicate", json=EVENT, headers={"X-Request-ID": REQUEST_ID})
    second = await lab.client.post("/api/v1/data/replicate", json=EVENT, headers={"X-Request-ID": REQUEST_ID})

    assert first.status_code == 201
    assert second.status_code == 201
    assert second.json()["gcp"] == "duplicate"
    assert second.json()["aws"] == "duplicate"
    assert len(lab.gcp.records) == 1
    assert len(lab.aws.records) == 1


async def test_replicate_stops_when_the_first_database_fails(lab: Lab) -> None:
    lab.gcp.fail = True

    response = await lab.client.post("/api/v1/data/replicate", json=EVENT, headers={"X-Request-ID": REQUEST_ID})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REPLICATION_FAILED"
    assert response.json()["error"]["request_id"] == REQUEST_ID
    assert lab.gcp.inserts == 1
    assert lab.aws.inserts == 0
    assert "://" not in response.text


async def test_replicate_reports_a_partial_write_without_credentials(lab: Lab) -> None:
    lab.aws.fail = True

    response = await lab.client.post("/api/v1/data/replicate", json=EVENT, headers={"X-Request-ID": REQUEST_ID})

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "REPLICATION_FAILED"
    assert lab.gcp.inserts == 1
    assert EVENT_ID in {str(key) for key in lab.gcp.records}
    assert lab.aws.records == {}
    lowered = response.text.lower()
    assert "password" not in lowered
    assert "postgresql" not in lowered
