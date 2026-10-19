from uuid import UUID

from app.core.errors import DatabaseUnavailableError
from app.services.audit_store import AuditRecord


class FakeAuditStore:
    def __init__(self, cloud: str, fail: bool = False) -> None:
        self.cloud = cloud
        self.fail = fail
        self.records: dict[UUID, AuditRecord] = {}
        self.inserts = 0
        self.pings = 0

    async def ping(self) -> None:
        self.pings += 1
        if self.fail:
            raise DatabaseUnavailableError(self.cloud)

    async def insert(self, record: AuditRecord) -> str:
        self.inserts += 1
        if self.fail:
            raise DatabaseUnavailableError(self.cloud)
        if record.event_id in self.records:
            return "duplicate"
        self.records[record.event_id] = record
        return "stored"


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now
