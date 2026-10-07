from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from app.api.deps import get_order_service, get_request_id
from app.schemas.error import ErrorResponse
from app.schemas.order import parse_order
from app.services.order_service import OrderService

router = APIRouter(prefix="/api/v1")


@router.post(
    "/orders",
    status_code=201,
    responses={
        400: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
        504: {"model": ErrorResponse},
    },
)
async def create_order(
    request: Request,
    request_id: str = Depends(get_request_id),
    order_service: OrderService = Depends(get_order_service),
) -> Response:
    order = parse_order(await request.body())
    result = await order_service.submit(order, request_id)
    return Response(
        content=result.body,
        status_code=result.status_code,
        media_type="application/json",
    )
