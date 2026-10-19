from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from app.api.deps import get_replication_service
from app.core.errors import AppError
from app.core.metrics import track_request
from app.core.responses import json_response
from app.schemas.error import ErrorResponse
from app.schemas.event import parse_replication
from app.services.replication_service import ReplicationService

router = APIRouter(prefix="/api/v1/data")


@router.post(
    "/replicate",
    status_code=201,
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def replicate(
    request: Request,
    service: ReplicationService = Depends(get_replication_service),
) -> Response:
    with track_request("replicate") as status:
        record = parse_replication(await request.body())
        try:
            written = await service.replicate(record)
        except AppError:
            raise
        status["result"] = "success"
        return json_response(
            201,
            {
                "event_id": str(record.event_id),
                "order_id": str(record.order_id),
                "status": "replicated",
                "gcp": written["gcp"],
                "aws": written["aws"],
            },
        )
