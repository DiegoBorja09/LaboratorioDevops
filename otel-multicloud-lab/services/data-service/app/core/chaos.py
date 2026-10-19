import asyncio
import secrets
import time
from collections.abc import Callable

from app.core.config import Settings
from app.core.errors import ChaosInjectedError


class ChaosController:
    def __init__(
        self,
        settings: Settings,
        clock: Callable[[], float] | None = None,
        random_source: Callable[[], float] | None = None,
    ) -> None:
        self._clock = clock or time.monotonic
        self._random = random_source or secrets.SystemRandom().random
        self._token = settings.chaos_token
        self._baseline_enabled = settings.chaos_enabled
        self._baseline_rate = settings.chaos_error_rate
        self._baseline_delay = settings.chaos_delay_ms
        self._enabled = settings.chaos_enabled
        self._error_rate = settings.chaos_error_rate if settings.chaos_enabled else 0.0
        self._delay_ms = settings.chaos_delay_ms if settings.chaos_enabled else 0
        self._expires_at: float | None = None

    def authorize(self, header: str | None) -> bool:
        if not self._token or not header:
            return False
        return secrets.compare_digest(header, self._token)

    def configure(self, error_rate: float, delay_ms: int, duration_seconds: float) -> None:
        self._enabled = True
        self._error_rate = error_rate
        self._delay_ms = delay_ms
        self._expires_at = self._clock() + duration_seconds

    def snapshot(self) -> dict[str, float | int | bool]:
        self._refresh()
        remaining = 0.0
        if self._expires_at is not None:
            remaining = max(self._expires_at - self._clock(), 0.0)
        return {
            "enabled": self._enabled,
            "error_rate": self._error_rate,
            "delay_ms": self._delay_ms,
            "duration_seconds": remaining,
        }

    async def before_write(self) -> None:
        self._refresh()
        if not self._enabled:
            return
        if self._delay_ms > 0:
            await asyncio.sleep(self._delay_ms / 1000)
        if self._random() < self._error_rate:
            raise ChaosInjectedError()

    def _refresh(self) -> None:
        if self._expires_at is None or self._clock() < self._expires_at:
            return
        self._expires_at = None
        self._enabled = self._baseline_enabled
        self._error_rate = self._baseline_rate if self._baseline_enabled else 0.0
        self._delay_ms = self._baseline_delay if self._baseline_enabled else 0
