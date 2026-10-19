from fastapi import APIRouter

from app.api.chaos import router as chaos_router
from app.api.data import router as data_router
from app.api.health import router as health_router

api_router = APIRouter()
api_router.include_router(health_router)
api_router.include_router(data_router)
api_router.include_router(chaos_router)
