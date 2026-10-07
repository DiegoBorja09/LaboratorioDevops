from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Order


class OrderRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, order: Order) -> Order:
        self._session.add(order)
        await self._session.commit()
        await self._session.refresh(order)
        return order

    async def get_by_id(self, order_id: UUID) -> Order | None:
        return await self._session.get(Order, order_id)

    async def list_all(self) -> list[Order]:
        result = await self._session.execute(select(Order).order_by(Order.created_at.desc()))
        return list(result.scalars().all())
