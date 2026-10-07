from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import Response

from app.api.deps import get_request_id, get_session
from app.core.errors import OrderNotFoundError
from app.core.responses import json_response
from app.repositories.order_repository import OrderRepository
from app.schemas.error import ErrorResponse
from app.schemas.order import OrderResponse, order_payload, parse_order, parse_order_id
from app.services.order_service import list_orders, process_order

router = APIRouter(prefix="/api/v1/orders")


@router.post(
    "/process",
    status_code=201,
    response_model=OrderResponse,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        500: {"model": ErrorResponse},
    },
)
async def process(
    request: Request,
    request_id: str = Depends(get_request_id),
    session: AsyncSession = Depends(get_session),
) -> Response:
    order = parse_order(await request.body())
    saved = await process_order(order, UUID(request_id), OrderRepository(session))
    return json_response(201, order_payload(saved))


@router.get(
    "",
    response_model=list[OrderResponse],
)
async def get_orders(session: AsyncSession = Depends(get_session)) -> Response:
    orders = await list_orders(OrderRepository(session))
    return json_response(200, [order_payload(order) for order in orders])


@router.get(
    "/{order_id}",
    response_model=OrderResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def get_order(
    order_id: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    saved = await OrderRepository(session).get_by_id(parse_order_id(order_id))
    if saved is None:
        raise OrderNotFoundError()
    return json_response(200, order_payload(saved))
