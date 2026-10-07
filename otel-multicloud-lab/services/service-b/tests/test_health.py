async def test_health(client) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "service-b",
        "database": "connected",
    }
    assert response.headers["X-Request-ID"]
