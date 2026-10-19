from fastapi import Request

from app.core.chaos import ChaosController
from app.core.context import request_id_var
from app.services.replication_service import ReplicationService


def get_request_id(request: Request) -> str:
    value = request_id_var.get()
    if value:
        return value
    return str(request.state.request_id)


def get_replication_service(request: Request) -> ReplicationService:
    return request.app.state.replication_service


def get_chaos(request: Request) -> ChaosController:
    return request.app.state.chaos
