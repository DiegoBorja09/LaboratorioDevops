from typing import Any

from starlette.responses import Response

from app.core.serialization import dumps


def error_payload(code: str, message: str, request_id: str) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "request_id": request_id,
        }
    }


def json_response(status_code: int, payload: Any) -> Response:
    return Response(
        content=dumps(payload),
        status_code=status_code,
        media_type="application/json",
    )
