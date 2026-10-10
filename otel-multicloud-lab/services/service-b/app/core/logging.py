import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.context import request_id_var

_LOG_FIELDS = ("request_id", "method", "path", "status_code", "duration_ms")


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if not getattr(record, "request_id", None):
            record.request_id = request_id_var.get()
        return True


class JsonFormatter(logging.Formatter):
    def __init__(self, service_name: str) -> None:
        super().__init__()
        self.service_name = service_name

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "service": self.service_name,
            "message": record.getMessage(),
        }
        for field in _LOG_FIELDS:
            value = getattr(record, field, None)
            if value is not None and value != "":
                payload[field] = value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def log_event(
    logger: logging.Logger,
    level: int,
    message: str,
    event_name: str,
    *,
    result: str | None = None,
    error_type: str | None = None,
    route: str | None = None,
    method: str | None = None,
) -> None:
    extra: dict[str, Any] = {"event.name": event_name}
    if route is not None:
        extra["http.route"] = route
    if method is not None:
        extra["http.request.method"] = method
    if result is not None:
        extra["result"] = result
    if error_type is not None:
        extra["error.type"] = error_type
    logger.log(level, message, extra=extra)


def configure_logging(service_name: str, level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))
    handler.addFilter(RequestContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "httpx",
        "httpcore",
        "sqlalchemy.engine",
        "asyncpg",
    ):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    logging.getLogger("sqlalchemy.engine").setLevel(logging.WARNING)
    logging.getLogger("asyncpg").setLevel(logging.WARNING)
    from app.core.telemetry import attach_log_handler

    attach_log_handler()


def build_uvicorn_log_config(service_name: str, level: str) -> dict[str, Any]:
    log_level = level.upper()
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "filters": {
            "request_context": {
                "()": "app.core.logging.RequestContextFilter",
            }
        },
        "formatters": {
            "json": {
                "()": "app.core.logging.JsonFormatter",
                "service_name": service_name,
            }
        },
        "handlers": {
            "default": {
                "class": "logging.StreamHandler",
                "formatter": "json",
                "filters": ["request_context"],
                "stream": "ext://sys.stdout",
            }
        },
        "loggers": {
            "uvicorn": {"handlers": [], "level": log_level, "propagate": True},
            "uvicorn.error": {"handlers": [], "level": log_level, "propagate": True},
            "uvicorn.access": {"handlers": [], "level": "WARNING", "propagate": True},
            "sqlalchemy.engine": {"handlers": [], "level": "WARNING", "propagate": True},
            "asyncpg": {"handlers": [], "level": "WARNING", "propagate": True},
        },
        "root": {"handlers": ["default"], "level": log_level},
    }
