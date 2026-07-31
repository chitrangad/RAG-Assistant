"""API health and readiness endpoints."""

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from src.config import settings
from src.database import get_db

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    """Basic liveness check — always returns OK if the server is running."""
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
    }


@router.get("/ready")
async def readiness_check(db: AsyncSession = Depends(get_db)):
    """Readiness check — verifies database connectivity."""
    try:
        await db.execute(text("SELECT 1"))
        db_status = "ok"
    except Exception:
        db_status = "unavailable"

    overall = "ok" if db_status == "ok" else "degraded"

    return {
        "status": overall,
        "checks": {
            "database": db_status,
        },
    }
