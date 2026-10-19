import json
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.core.errors import AppError
from app.core.serialization import loads
from app.services.audit_store import AuditRecord


class ReplicationRequest(BaseModel):
    event_id: UUID
    order_id: UUID
    source_service: str = Field(min_length=1, max_length=64)
    status: str = Field(min_length=1, max_length=32)

    model_config = ConfigDict(extra="ignore")

    def record(self) -> AuditRecord:
        return AuditRecord(
            event_id=self.event_id,
            order_id=self.order_id,
            source_service=self.source_service,
            status=self.status,
        )


def parse_replication(raw: bytes) -> AuditRecord:
    if not raw:
        raise AppError("VALIDATION_ERROR", "El cuerpo de la solicitud no es JSON válido", 422)
    try:
        data: Any = loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise AppError(
            "VALIDATION_ERROR",
            "El cuerpo de la solicitud no es JSON válido",
            422,
        ) from exc
    if not isinstance(data, dict):
        raise AppError("VALIDATION_ERROR", "La solicitud contiene datos inválidos", 422)
    try:
        return ReplicationRequest.model_validate(data).record()
    except ValidationError as exc:
        raise AppError("VALIDATION_ERROR", "La solicitud contiene datos inválidos", 422) from exc
