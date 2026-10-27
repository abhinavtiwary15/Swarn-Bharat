"""Health-check endpoints for liveness and readiness."""

from __future__ import annotations

import logging

import redis.exceptions
from fastapi import APIRouter, Depends, Response, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from swarnbharat_shared.common import ErrorCode, ErrorDetail, HealthEnvelope, HealthStatus

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.redis import redis_rl

logger = logging.getLogger(__name__)

router = APIRouter()


async def _check_dependencies(
    db: AsyncSession,
) -> HealthStatus:
    db_ok = True
    redis_ok = True

    try:
        await db.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Database health check probe failed: %s", exc)
        db_ok = False

    try:
        await redis_rl.ping()
    except (redis.exceptions.RedisError, OSError) as exc:
        logger.warning("Redis health check probe failed: %s", exc)
        redis_ok = False

    return HealthStatus(
        status="ok" if (db_ok and redis_ok) else "degraded",
        version=settings.API_VERSION,
        db_ok=db_ok,
        redis_ok=redis_ok,
    )


@router.get(
    "/live",
    response_model=HealthEnvelope,
    summary="Liveness probe",
    operation_id="health-live",
)
async def live() -> HealthEnvelope:
    """Returns 200 OK as long as the application process is running."""
    return HealthEnvelope(
        success=True,
        data=HealthStatus(
            status="ok",
            version=settings.API_VERSION,
            db_ok=True,
            redis_ok=True,
        ),
    )


@router.get(
    "/ready",
    response_model=HealthEnvelope,
    summary="Readiness probe",
    operation_id="health-ready",
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": HealthEnvelope,
            "description": "Dependencies degraded or unreachable",
        }
    },
)
async def ready(
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> HealthEnvelope:
    """Readiness probe returning 503 when downstream dependencies are degraded."""
    data = await _check_dependencies(db)
    if data.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return HealthEnvelope(
            success=False,
            data=data,
            error=ErrorDetail(
                code=ErrorCode.SERVICE_UNAVAILABLE,
                message="Dependencies degraded or unreachable.",
            ),
        )
    return HealthEnvelope(success=True, data=data)
