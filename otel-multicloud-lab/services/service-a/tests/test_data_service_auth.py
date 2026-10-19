import json
from types import SimpleNamespace

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import create_app
from app.services.id_token import GoogleIdTokenProvider, IdTokenError

REQUEST_ID = "11111111-1111-1111-1111-111111111111"
ORDER = {"customer_id": "customer-001", "amount": 150000.50, "currency": "cop"}
TRACEPARENT = "00-0123456789abcdef0123456789abcdef-0123456789abcdef-01"
TOKEN = "test-id-token"
AUDIENCE = "https://otel-multicloud-lab-data-service.example.run.app"


def _processed_body() -> bytes:
    return (
        b'{"id":"22222222-2222-2222-2222-222222222222","status":"PROCESSED"}'
    )


def _settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "service_name": "service-a",
        "service_b_url": "http://service-b:8080",
        "service_b_timeout_seconds": 5,
        "data_service_url": "http://data-service:8080/",
        "data_service_audience": "",
        "data_service_auth_enabled": False,
        "log_level": "INFO",
    }
    values.update(overrides)
    return Settings(**values)


class _Tokens:
    def __init__(self, token: str = TOKEN, fail: bool = False) -> None:
        self.token = token
        self.fail = fail
        self.calls = 0

    async def get_token(self) -> str:
        self.calls += 1
        if self.fail:
            raise RuntimeError(f"metadata {self.token}")
        return self.token


def _handler(calls: list[httpx.Request]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("/replicate"):
            return httpx.Response(201, json={"status": "replicated"})
        return httpx.Response(201, content=_processed_body(), headers={"content-type": "application/json"})

    return httpx.MockTransport(handle)


async def _post(settings: Settings, token_provider: _Tokens | None = None) -> tuple[httpx.Response, list[httpx.Request]]:
    calls: list[httpx.Request] = []
    application = create_app(
        settings=settings,
        transport=_handler(calls),
        token_provider=token_provider,
    )
    async with AsyncClient(transport=ASGITransport(app=application), base_url="http://test") as client:
        response = await client.post(
            "/api/v1/orders",
            json=ORDER,
            headers={
                "X-Request-ID": REQUEST_ID,
                "traceparent": TRACEPARENT,
                "baggage": "lab=demo",
            },
        )
    await application.state.http_client.aclose()
    return response, calls


async def test_auth_disabled_does_not_ask_for_google_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_metadata(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no se debe contactar al metadata server")

    monkeypatch.setattr("google.auth.transport.requests.Request", fail_metadata)
    response, calls = await _post(_settings(data_service_auth_enabled=False))
    replicate = calls[1]

    assert response.status_code == 201
    assert "authorization" not in {key.lower() for key in replicate.headers}
    assert replicate.headers["X-Request-ID"] == REQUEST_ID


async def test_auth_enabled_sends_bearer_without_dropping_propagation_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def inject(carrier: dict[str, str]) -> None:
        carrier["traceparent"] = TRACEPARENT
        carrier["baggage"] = "lab=demo"

    monkeypatch.setattr("app.services.order_service.inject", inject)
    tokens = _Tokens()
    response, calls = await _post(
        _settings(data_service_auth_enabled=True, data_service_audience=AUDIENCE),
        tokens,
    )
    service_b = calls[0]
    replicate = calls[1]

    assert response.status_code == 201
    assert tokens.calls == 1
    assert replicate.headers["Authorization"] == f"Bearer {TOKEN}"
    assert replicate.headers["X-Request-ID"] == REQUEST_ID
    assert replicate.headers["traceparent"] == TRACEPARENT
    assert replicate.headers["baggage"] == "lab=demo"
    assert replicate.url.path == "/api/v1/data/replicate"
    assert "authorization" not in {key.lower() for key in service_b.headers}
    assert TOKEN not in response.text


async def test_token_failure_returns_502_without_the_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("app.services.order_service.inject", lambda _carrier: None)
    response, calls = await _post(
        _settings(data_service_auth_enabled=True, data_service_audience=AUDIENCE),
        _Tokens(fail=True),
    )

    assert [request.url.path for request in calls] == ["/api/v1/orders/process"]
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "DATA_SERVICE_UNAVAILABLE"
    assert TOKEN not in response.text
    assert "metadata" not in response.text


def test_empty_audience_uses_the_base_url_without_changing_the_host() -> None:
    settings = _settings(
        data_service_url="HTTPS://Data-Service.Example.run.app/",
        data_service_audience="   ",
        data_service_auth_enabled=True,
    )

    assert settings.data_service_url == "HTTPS://Data-Service.Example.run.app"
    assert settings.data_service_token_audience == "HTTPS://Data-Service.Example.run.app"


async def test_provider_caches_a_valid_token_and_does_not_call_metadata() -> None:
    audiences: list[str] = []

    def loader(audience: str) -> SimpleNamespace:
        audiences.append(audience)
        return SimpleNamespace(token=TOKEN, valid=True)

    provider = GoogleIdTokenProvider("HTTPS://Data-Service.Example.run.app/", loader=loader)

    assert provider.audience == "HTTPS://Data-Service.Example.run.app"
    assert await provider.get_token() == TOKEN
    assert await provider.get_token() == TOKEN
    assert audiences == [provider.audience]


async def test_provider_refreshes_without_decoding_when_the_cached_token_expires() -> None:
    calls = {"count": 0}

    def loader(_audience: str) -> SimpleNamespace:
        calls["count"] += 1
        return SimpleNamespace(token=TOKEN, valid=False)

    provider = GoogleIdTokenProvider(AUDIENCE, loader=loader)
    assert await provider.get_token() == TOKEN
    assert await provider.get_token() == TOKEN
    assert calls["count"] == 2


def test_metadata_loader_is_not_invoked_by_the_injected_provider(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_metadata(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no se debe contactar al metadata server")

    monkeypatch.setattr("google.auth.transport.requests.Request", fail_metadata)
    monkeypatch.setattr(
        "app.services.id_token._load_metadata_credentials",
        fail_metadata,
    )
    provider = GoogleIdTokenProvider(AUDIENCE, loader=lambda _audience: SimpleNamespace(token=TOKEN, valid=True))
    assert provider._loader("https://unused.example").token == TOKEN


async def test_loader_errors_do_not_surface_the_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    def loader(_audience: str) -> SimpleNamespace:
        raise RuntimeError(f"fallo con {TOKEN}")

    provider = GoogleIdTokenProvider(AUDIENCE, loader=loader)
    with pytest.raises(IdTokenError) as caught:
        await provider.get_token()

    assert TOKEN not in str(caught.value)
    assert caught.value.__cause__ is None
    assert json.dumps({"error": str(caught.value)})
