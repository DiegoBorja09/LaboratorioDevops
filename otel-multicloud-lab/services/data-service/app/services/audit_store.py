from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from uuid import UUID

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.sql import text

from app.core.errors import DatabaseUnavailableError
from app.models.audit_event import AuditEvent


@dataclass(frozen=True, slots=True)
class AuditRecord:
    event_id: UUID
    order_id: UUID
    source_service: str
    status: str


class AuditStore(Protocol):
    cloud: str

    async def ping(self) -> None: ...

    async def insert(self, record: AuditRecord) -> str: ...


class SqlAuditStore:
    def __init__(self, cloud: str, session_factory: async_sessionmaker) -> None:
        self.cloud = cloud
        self._session_factory = session_factory

    async def ping(self) -> None:
        try:
            async with self._session_factory() as session:
                await session.execute(text("SELECT 1"))
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError(self.cloud) from exc

    async def insert(self, record: AuditRecord) -> str:
        try:
            async with self._session_factory() as session:
                existing = await session.get(AuditEvent, record.event_id)
                if existing is not None:
                    return "duplicate"
                session.add(
                    AuditEvent(
                        event_id=record.event_id,
                        order_id=record.order_id,
                        source_service=record.source_service,
                        status=record.status,
                        created_at=datetime.now(timezone.utc),
                    )
                )
                await session.commit()
                return "stored"
        except IntegrityError:
            return "duplicate"
        except SQLAlchemyError as exc:
            raise DatabaseUnavailableError(self.cloud) from exc


class UnavailableAuditStore:
    def __init__(self, cloud: str) -> None:
        self.cloud = cloud

    async def ping(self) -> None:
        raise DatabaseUnavailableError(self.cloud)

    async def insert(self, record: AuditRecord) -> str:
        del record
        raise DatabaseUnavailableError(self.cloud)
