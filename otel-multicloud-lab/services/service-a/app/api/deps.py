from fastapi import Request

from app.core.context import request_id_var
from app.services.order_service import OrderService


def get_request_id(request: Request) -> str:
    value = request_id_var.get()
    if value:
        return value
    return str(request.state.request_id)


def get_order_service(request: Request) -> OrderService:
    return request.app.state.order_service
