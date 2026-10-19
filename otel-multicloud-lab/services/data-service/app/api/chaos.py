from pydantic import ValidationError
from fastapi import APIRouter, Depends, Request
from starlette.responses import Response

from app.api.deps import get_chaos
from app.core.chaos import ChaosController
from app.core.errors import AppError, ChaosUnauthorizedError
from app.core.responses import json_response
from app.core.serialization import loads
from app.schemas.chaos import ChaosCommand
from app.schemas.error import ErrorResponse

router = APIRouter(prefix="/internal")
_TOKEN_HEADER = "X-Chaos-Token"


@router.post(
    "/chaos",
    responses={
        401: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
    },
)
async def configure_chaos(
    request: Request,
    chaos: ChaosController = Depends(get_chaos),
) -> Response:
    if not chaos.authorize(request.headers.get(_TOKEN_HEADER)):
        raise ChaosUnauthorizedError()
    try:
        command = ChaosCommand.model_validate(loads(await request.body()))
    except (ValidationError, ValueError) as exc:
        raise AppError("VALIDATION_ERROR", "La solicitud contiene datos inválidos", 422) from exc
    chaos.configure(command.error_rate, command.delay_ms, command.duration_seconds)
    return json_response(200, chaos.snapshot())
