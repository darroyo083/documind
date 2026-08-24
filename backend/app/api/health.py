from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.config import settings
from app.infrastructure.database import engine

router = APIRouter()


@router.get("/health")
async def health():
    """Liveness probe: process is up. Deliberately database-independent."""
    return {"status": "ok", "version": settings.app_version}


@router.get("/health/ready")
async def ready():
    """Readiness probe for the active deployment mode."""
    if settings.public_demo_mode:
        return {
            "status": "ok",
            "version": settings.app_version,
            "mode": "public-demo",
            "public_demo": True,
            "database": "not_required",
        }

    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except Exception:
        return JSONResponse(
            status_code=503,
            content={
                "status": "degraded",
                "version": settings.app_version,
                "database": "unreachable",
            },
        )
    return {"status": "ok", "version": settings.app_version, "database": "reachable"}
