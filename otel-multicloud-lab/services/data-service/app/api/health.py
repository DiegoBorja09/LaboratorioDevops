from fastapi import APIRouter, Depends
from starlette.responses import Response

from app.api.deps import get_replication_service
from app.core.metrics import track_request
from app.core.responses import json_response
from app.services.replication_service import ReplicationService

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "healthy", "service": "data-service"}


@router.get("/ready")
async def ready(service: ReplicationService = Depends(get_replication_service)) -> Response:
    with track_request("ready") as status:
        databases = await service.ready()
        available = all(value == "connected" for value in databases.values())
        status["result"] = "success" if available else "error"
        await service.readiness_log(available)
        return json_response(
            200 if available else 503,
            {
                "status": "ready" if available else "unavailable",
                "databases": databases,
            },
        )
