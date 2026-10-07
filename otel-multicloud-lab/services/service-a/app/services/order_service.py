import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP

import httpx

from app.core.config import Settings
from app.core.errors import AppError, ServiceTimeoutError, ServiceUnavailableError
from app.core.serialization import dumps
from app.schemas.order import OrderCreate

logger = logging.getLogger("app.orders")
_CENT = Decimal("0.01")


def validate_order(order: OrderCreate) -> OrderCreate:
    if not order.customer_id:
        raise AppError("VALIDATION_ERROR", "customer_id es obligatorio", 422)
    normalized_amount = order.amount.quantize(_CENT, rounding=ROUND_HALF_UP)
    if normalized_amount <= 0:
        raise AppError("VALIDATION_ERROR", "amount debe ser mayor que cero", 422)
    currency = order.currency.upper()
    if len(currency) != 3:
        raise AppError(
            "VALIDATION_ERROR",
            "currency debe tener exactamente tres caracteres",
            422,
        )
    return order.model_copy(update={"amount": normalized_amount, "currency": currency})


@dataclass(frozen=True, slots=True)
class DownstreamResult:
    status_code: int
    body: bytes


class OrderService:
    def __init__(self, client: httpx.AsyncClient, settings: Settings) -> None:
        self._client = client
        self._base_url = settings.service_b_url.rstrip("/")
        self._timeout = settings.service_b_timeout_seconds

    async def submit(self, order: OrderCreate, request_id: str) -> DownstreamResult:
        validated = validate_order(order)
        url = f"{self._base_url}/api/v1/orders/process"
        body = dumps(
            {
                "customer_id": validated.customer_id,
                "amount": validated.amount,
                "currency": validated.currency,
            }
        )
        try:
            response = await self._client.post(
                url,
                content=body.encode("utf-8"),
                headers={
                    "Content-Type": "application/json",
                    "X-Request-ID": request_id,
                },
                timeout=httpx.Timeout(self._timeout),
            )
        except httpx.TimeoutException as exc:
            raise ServiceTimeoutError() from exc
        except httpx.RequestError as exc:
            raise ServiceUnavailableError() from exc

        if response.status_code >= 500:
            raise ServiceUnavailableError()

        logger.info(
            "Orden enviada a service-b",
            extra={
                "request_id": request_id,
                "method": "POST",
                "path": "/api/v1/orders/process",
                "status_code": response.status_code,
            },
        )
        return DownstreamResult(status_code=response.status_code, body=response.content)
