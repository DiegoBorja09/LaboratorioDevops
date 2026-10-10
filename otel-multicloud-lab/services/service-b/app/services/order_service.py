import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4

from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode

from app.core.logging import log_event
from app.core.metrics import track_processing
from app.models.order import Order
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreate

logger = logging.getLogger("app.orders")
_CENT = Decimal("0.01")
ORDER_STATUS_PROCESSED = "PROCESSED"
_ROUTE = "/api/v1/orders/process"
_METHOD = "POST"


async def process_order(
    order: OrderCreate,
    request_id: UUID,
    repository: OrderRepository,
) -> Order:
    tracer = trace.get_tracer("service-b")
    with track_processing() as status:
        with tracer.start_as_current_span("process_order") as span:
            log_event(
                logger,
                logging.INFO,
                "Procesamiento de pedido iniciado",
                "order.processing.started",
                route=_ROUTE,
                method=_METHOD,
            )
            try:
                entity = Order(
                    id=uuid4(),
                    customer_id=order.customer_id,
                    amount=order.amount.quantize(_CENT, rounding=ROUND_HALF_UP),
                    currency=order.currency.upper(),
                    status=ORDER_STATUS_PROCESSED,
                    request_id=request_id,
                    created_at=datetime.now(timezone.utc),
                )
                saved = await repository.add(entity)
            except Exception as exc:
                span.set_attribute("order.processing.result", "error")
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR))
                log_event(
                    logger,
                    logging.ERROR,
                    "Procesamiento de pedido fallido",
                    "order.processing.failed",
                    result="error",
                    error_type=exc.__class__.__name__,
                    route=_ROUTE,
                    method=_METHOD,
                )
                raise
            span.set_attribute("order.currency", saved.currency)
            span.set_attribute("order.processing.result", "success")
            span.set_attribute("order.status", saved.status)
            log_event(
                logger,
                logging.INFO,
                "Procesamiento de pedido completado",
                "order.processing.completed",
                result="success",
                route=_ROUTE,
                method=_METHOD,
            )
            status["code"] = 201
            return saved


async def list_orders(repository: OrderRepository) -> list[Order]:
    return await repository.list_all()
