import logging

from app.core.chaos import ChaosController
from app.core.errors import ChaosInjectedError, DatabaseUnavailableError, ReplicationFailedError
from app.core.logging import log_event
from app.core.metrics import record_chaos_injection, record_database_operation, record_replication_failure
from app.services.audit_store import AuditRecord, AuditStore

logger = logging.getLogger("app.replication")
_ROUTE = "/api/v1/data/replicate"
_READY_ROUTE = "/ready"


class ReplicationService:
    def __init__(self, gcp: AuditStore, aws: AuditStore, chaos: ChaosController) -> None:
        self._stores = (("gcp", gcp), ("aws", aws))
        self._chaos = chaos

    async def ready(self) -> dict[str, str]:
        status: dict[str, str] = {}
        for cloud, store in self._stores:
            try:
                await store.ping()
            except DatabaseUnavailableError:
                record_database_operation(cloud, "select", "error")
                status[cloud] = "unavailable"
                continue
            record_database_operation(cloud, "select", "success")
            status[cloud] = "connected"
        return status

    async def replicate(self, record: AuditRecord) -> dict[str, str]:
        try:
            await self._chaos.before_write()
        except ChaosInjectedError:
            record_chaos_injection()
            log_event(
                logger,
                logging.ERROR,
                "Se inyectó un error controlado antes de escribir",
                "chaos.injected_error",
                result="error",
                error_type="CHAOS_INJECTED",
                route=_ROUTE,
                method="POST",
            )
            raise
        written: dict[str, str] = {}
        for cloud, store in self._stores:
            try:
                written[cloud] = await store.insert(record)
            except DatabaseUnavailableError:
                record_database_operation(cloud, "insert", "error")
                record_replication_failure(cloud)
                log_event(
                    logger,
                    logging.ERROR,
                    "Replicación incompleta",
                    "data.replication.failed",
                    result="error",
                    error_type="REPLICATION_FAILED",
                    route=_ROUTE,
                    method="POST",
                )
                raise ReplicationFailedError() from None
            record_database_operation(cloud, "insert", "success")
        log_event(
            logger,
            logging.INFO,
            "Evento replicado",
            "data.replication.completed",
            result="success",
            route=_ROUTE,
            method="POST",
        )
        return written

    async def readiness_log(self, ready: bool) -> None:
        log_event(
            logger,
            logging.INFO if ready else logging.ERROR,
            "Readiness de bases evaluado",
            "data.readiness.completed",
            result="success" if ready else "error",
            route=_READY_ROUTE,
            method="GET",
        )
