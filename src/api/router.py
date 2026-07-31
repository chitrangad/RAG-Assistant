"""Main API router — aggregates all sub-routers."""

from fastapi import APIRouter

from src.api.health import router as health_router
from src.api.ingestion import router as ingestion_router

api_router = APIRouter(prefix="/api")
api_router.include_router(health_router)
api_router.include_router(ingestion_router)

from src.api.chat import router as chat_router
from src.api.admin import router as admin_router

api_router.include_router(chat_router)
api_router.include_router(admin_router)
