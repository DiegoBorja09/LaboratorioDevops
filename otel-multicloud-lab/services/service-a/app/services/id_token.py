import asyncio
import logging
from collections.abc import Callable
from typing import Protocol

logger = logging.getLogger("app.auth")


class IdTokenError(Exception):
    def __init__(self) -> None:
        super().__init__("No fue posible obtener el ID token")


class IdTokenProvider(Protocol):
    async def get_token(self) -> str:
        """Devuelve un ID token vigente. No incluye el esquema Bearer."""


class GoogleIdTokenProvider:
    """Pide el ID token de la identidad de Cloud Run y lo reutiliza mientras siga vigente."""

    def __init__(self, audience: str, loader: Callable[[str], object] | None = None) -> None:
        self._audience = audience.rstrip("/")
        self._loader = loader or _load_metadata_credentials
        self._credentials: object | None = None
        self._lock = asyncio.Lock()

    @property
    def audience(self) -> str:
        return self._audience

    async def get_token(self) -> str:
        async with self._lock:
            return await asyncio.to_thread(self._token)

    def _token(self) -> str:
        cached = self._credentials
        if cached is not None and bool(getattr(cached, "valid", False)):
            token = getattr(cached, "token", None)
            if isinstance(token, str) and token:
                return token
        try:
            credentials = self._loader(self._audience)
        except IdTokenError:
            raise
        except Exception as exc:
            logger.error(
                "No fue posible obtener el ID token",
                extra={"error.type": type(exc).__name__},
            )
            raise IdTokenError() from None
        token = getattr(credentials, "token", None)
        if not isinstance(token, str) or not token:
            logger.error(
                "No fue posible obtener el ID token",
                extra={"error.type": "IdTokenError"},
            )
            raise IdTokenError()
        self._credentials = credentials
        return token


def _load_metadata_credentials(audience: str) -> object:
    from google.auth.compute_engine import IDTokenCredentials
    from google.auth.transport.requests import Request

    request = Request()
    credentials = IDTokenCredentials(
        request,
        audience,
        use_metadata_identity_endpoint=True,
    )
    credentials.refresh(request)
    return credentials
