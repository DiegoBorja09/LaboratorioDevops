import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import Response

from app.core.context import request_id_var
from app.core.errors import AppError
from app.core.responses import error_payload, json_response

logger = logging.getLogger("app.errors")


def current_request_id(request: Request) -> str:
    request_id = getattr(request.state, "request_id", None)
    if isinstance(request_id, str) and request_id:
        return request_id
    value = request_id_var.get()
    if value:
        return value
    return "unavailable"


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> Response:
        request_id = current_request_id(request)
        if exc.status_code >= 500:
            logger.error(
                exc.message,
                extra={"request_id": request_id, "status_code": exc.status_code},
            )
        return json_response(
            exc.status_code,
            error_payload(exc.code, exc.message, request_id),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(request: Request, exc: RequestValidationError) -> Response:
        del exc
        return json_response(
            422,
            error_payload(
                "VALIDATION_ERROR",
                "La solicitud contiene datos inválidos",
                current_request_id(request),
            ),
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(request: Request, exc: HTTPException) -> Response:
        message = exc.detail if isinstance(exc.detail, str) else "No fue posible completar la operación"
        code = "INTERNAL_ERROR" if exc.status_code >= 500 else "HTTP_ERROR"
        return json_response(
            exc.status_code,
            error_payload(code, message, current_request_id(request)),
        )

    @app.exception_handler(SQLAlchemyError)
    async def handle_database_error(request: Request, exc: SQLAlchemyError) -> Response:
        logger.error(
            "Error de base de datos: %s",
            exc.__class__.__name__,
            extra={"request_id": current_request_id(request)},
        )
        return json_response(
            500,
            error_payload(
                "INTERNAL_ERROR",
                "No fue posible completar la operación",
                current_request_id(request),
            ),
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> Response:
        logger.error(
            "Error no controlado: %s",
            exc.__class__.__name__,
            extra={"request_id": current_request_id(request)},
        )
        return json_response(
            500,
            error_payload(
                "INTERNAL_ERROR",
                "No fue posible completar la operación",
                current_request_id(request),
            ),
        )
