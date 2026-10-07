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
        return dumps_log(payload)


def dumps_log(payload: dict[str, Any]) -> str:
    import json

    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(service_name: str, level: str) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service_name))
    handler.addFilter(RequestContextFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    for name in ("uvicorn", "uvicorn.error", "uvicorn.access", "httpx", "httpcore"):
        logger = logging.getLogger(name)
        logger.handlers.clear()
        logger.propagate = True

    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


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
            "httpx": {"handlers": [], "level": "WARNING", "propagate": True},
            "httpcore": {"handlers": [], "level": "WARNING", "propagate": True},
        },
        "root": {"handlers": ["default"], "level": log_level},
    }
