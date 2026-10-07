import logging
from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from uuid import UUID, uuid4

from app.models.order import Order
from app.repositories.order_repository import OrderRepository
from app.schemas.order import OrderCreate

logger = logging.getLogger("app.orders")
_CENT = Decimal("0.01")
ORDER_STATUS_PROCESSED = "PROCESSED"


async def process_order(
    order: OrderCreate,
    request_id: UUID,
    repository: OrderRepository,
) -> Order:
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
    logger.info("Orden procesada", extra={"request_id": str(request_id)})
    return saved


async def list_orders(repository: OrderRepository) -> list[Order]:
    return await repository.list_all()
