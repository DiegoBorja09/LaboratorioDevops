import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from uuid import uuid4

import httpx
from opentelemetry import trace
from opentelemetry.propagate import inject
from opentelemetry.trace import Status, StatusCode

from app.core.config import Settings
from app.core.errors import (
    AppError,
    DataServiceError,
    DataServiceTimeoutError,
    ServiceTimeoutError,
    ServiceUnavailableError,
)
from app.core.logging import log_event
from app.core.serialization import dumps, loads
from app.schemas.order import OrderCreate
from app.services.id_token import IdTokenError, IdTokenProvider

logger = logging.getLogger("app.orders")
_CENT = Decimal("0.01")
_ROUTE = "/api/v1/orders"
_METHOD = "POST"


def validate_order(order: OrderCreate) -> OrderCreate:
    tracer = trace.get_tracer("service-a")
    with tracer.start_as_current_span("validate_order") as span:
        try:
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
            validated = order.model_copy(update={"amount": normalized_amount, "currency": currency})
        except AppError as exc:
            span.set_attribute("order.validation.result", "error")
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR))
            log_event(
                logger,
                logging.WARNING,
                "Validación de pedido finalizada",
                "order.validation.completed",
                result="error",
                error_type=exc.code,
                route=_ROUTE,
                method=_METHOD,
            )
            raise
        span.set_attribute("order.currency", validated.currency)
        span.set_attribute("order.validation.result", "success")
        log_event(
            logger,
            logging.INFO,
            "Validación de pedido finalizada",
            "order.validation.completed",
            result="success",
            route=_ROUTE,
            method=_METHOD,
        )
        return validated


@dataclass(frozen=True, slots=True)
class DownstreamResult:
    status_code: int
    body: bytes


class OrderService:
    def __init__(
        self,
        client: httpx.AsyncClient,
        settings: Settings,
        token_provider: IdTokenProvider | None = None,
    ) -> None:
        self._client = client
        self._base_url = settings.service_b_url.rstrip("/")
        self._timeout = settings.service_b_timeout_seconds
        self._data_service_url = settings.data_service_url or ""
        self._data_service_timeout = settings.data_service_timeout_seconds
        self._authenticate_data_service = settings.data_service_auth_enabled
        self._token_provider = token_provider

    async def submit(self, order: OrderCreate, request_id: str) -> DownstreamResult:
        validated = validate_order(order)
        log_event(
            logger,
            logging.INFO,
            "Solicitud de pedido recibida",
            "order.request.received",
            result="success",
            route=_ROUTE,
            method=_METHOD,
        )
        url = f"{self._base_url}/api/v1/orders/process"
        body = dumps(
            {
                "customer_id": validated.customer_id,
                "amount": validated.amount,
                "currency": validated.currency,
            }
        )
        log_event(
            logger,
            logging.INFO,
            "Reenvío hacia service-b iniciado",
            "order.forward.started",
            result="success",
            route=_ROUTE,
            method=_METHOD,
        )
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
        }
        inject(headers)
        try:
            response = await self._client.post(
                url,
                content=body.encode("utf-8"),
                headers=headers,
                timeout=httpx.Timeout(self._timeout),
            )
        except httpx.TimeoutException as exc:
            log_event(
                logger,
                logging.ERROR,
                "Solicitud de pedido fallida",
                "order.request.failed",
                result="error",
                error_type="SERVICE_B_TIMEOUT",
                route=_ROUTE,
                method=_METHOD,
            )
            raise ServiceTimeoutError() from exc
        except httpx.RequestError as exc:
            log_event(
                logger,
                logging.ERROR,
                "Solicitud de pedido fallida",
                "order.request.failed",
                result="error",
                error_type="SERVICE_B_UNAVAILABLE",
                route=_ROUTE,
                method=_METHOD,
            )
            raise ServiceUnavailableError() from exc

        if response.status_code >= 500:
            log_event(
                logger,
                logging.ERROR,
                "Solicitud de pedido fallida",
                "order.request.failed",
                result="error",
                error_type="SERVICE_B_UNAVAILABLE",
                route=_ROUTE,
                method=_METHOD,
            )
            raise ServiceUnavailableError()

        if self._data_service_url and response.status_code < 300:
            await self._replicate(response.content, request_id)

        log_event(
            logger,
            logging.INFO,
            "Solicitud de pedido completada",
            "order.request.completed",
            result="success",
            route=_ROUTE,
            method=_METHOD,
        )
        return DownstreamResult(status_code=response.status_code, body=response.content)

    async def _replicate(self, body: bytes, request_id: str) -> None:
        payload = dumps(
            {
                "event_id": str(uuid4()),
                "order_id": self._order_id(body),
                "source_service": "service-a",
                "status": "created",
            }
        )
        headers = {
            "Content-Type": "application/json",
            "X-Request-ID": request_id,
        }
        inject(headers)
        if self._authenticate_data_service:
            headers["Authorization"] = f"Bearer {await self._id_token()}"
        try:
            response = await self._client.post(
                f"{self._data_service_url}/api/v1/data/replicate",
                content=payload.encode("utf-8"),
                headers=headers,
                timeout=httpx.Timeout(self._data_service_timeout),
            )
        except httpx.TimeoutException as exc:
            log_event(
                logger,
                logging.ERROR,
                "Replicación de auditoría fallida",
                "order.replication.failed",
                result="error",
                error_type="DATA_SERVICE_TIMEOUT",
                route=_ROUTE,
                method=_METHOD,
            )
            raise DataServiceTimeoutError() from exc
        except httpx.RequestError as exc:
            log_event(
                logger,
                logging.ERROR,
                "Replicación de auditoría fallida",
                "order.replication.failed",
                result="error",
                error_type="DATA_SERVICE_UNAVAILABLE",
                route=_ROUTE,
                method=_METHOD,
            )
            raise DataServiceError() from exc
        if response.status_code >= 400:
            log_event(
                logger,
                logging.ERROR,
                "Replicación de auditoría fallida",
                "order.replication.failed",
                result="error",
                error_type="DATA_SERVICE_UNAVAILABLE",
                route=_ROUTE,
                method=_METHOD,
            )
            raise DataServiceError()

    async def _id_token(self) -> str:
        if self._token_provider is None:
            logger.error(
                "No fue posible obtener el ID token",
                extra={"error.type": "IdTokenError"},
            )
            raise DataServiceError()
        try:
            return await self._token_provider.get_token()
        except IdTokenError:
            raise DataServiceError() from None
        except Exception as exc:
            logger.error(
                "No fue posible obtener el ID token",
                extra={"error.type": type(exc).__name__},
            )
            raise DataServiceError() from None

    @staticmethod
    def _order_id(body: bytes) -> str:
        try:
            payload = loads(body)
        except (ValueError, UnicodeError) as exc:
            raise DataServiceError() from exc
        order_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(order_id, str) or not order_id:
            raise DataServiceError()
        return order_id
