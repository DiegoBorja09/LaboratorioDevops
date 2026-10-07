import logging
import time
from uuid import UUID, uuid4

from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.context import request_id_var
from app.core.responses import error_payload, json_response

logger = logging.getLogger("app.access")
REQUEST_ID_HEADER = "X-Request-ID"


def resolve_request_id(raw_header: str | None) -> tuple[str, bool]:
    if raw_header is None or not raw_header.strip():
        return str(uuid4()), False
    try:
        return str(UUID(raw_header.strip())), False
    except ValueError:
        return str(uuid4()), True


class RequestContextMiddleware:
    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope)
        request_id, invalid = resolve_request_id(request.headers.get(REQUEST_ID_HEADER))
        token = request_id_var.set(request_id)
        status_code = 500
        started = time.perf_counter()

        async def send_wrapper(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers[REQUEST_ID_HEADER] = request_id
            await send(message)

        try:
            if "state" not in scope:
                scope["state"] = {}
            scope["state"]["request_id"] = request_id
            if invalid:
                response = json_response(
                    400,
                    error_payload(
                        "INVALID_REQUEST_ID",
                        "X-Request-ID debe ser un UUID válido",
                        request_id,
                    ),
                )
                await response(scope, receive, send_wrapper)
                return
            await self.app(scope, receive, send_wrapper)
        finally:
            duration_ms = int((time.perf_counter() - started) * 1000)
            logger.info(
                "Solicitud procesada",
                extra={
                    "request_id": request_id,
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )
            request_id_var.reset(token)
