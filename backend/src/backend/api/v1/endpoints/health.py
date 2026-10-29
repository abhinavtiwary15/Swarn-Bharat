"""Health-check endpoints for liveness and readiness."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, status
from redis.exceptions import RedisError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.errors import ApiError
from backend.core.redis import redis_rl
from swarnbharat_shared.common import (
    ErrorCode,
    ErrorResponse,
    HealthEnvelope,
    HealthStatus,
)

logger = logging.getLogger(__name__)

router = APIRouter()


async def _check_dependencies(
    db: AsyncSession,
) -> tuple[bool, list[str]]:
    unavailable: list[str] = []

    try:
        await db.execute(text("SELECT 1"))
    except (SQLAlchemyError, OSError) as exc:
        logger.warning("Database probe failed: %s", type(exc).__name__)
        unavailable.append("database")

    try:
        await redis_rl.ping()
    except (RedisError, OSError) as exc:
        logger.warning("Redis probe failed: %s", type(exc).__name__)
        unavailable.append("redis")

    return len(unavailable) == 0, unavailable


@router.get(
    "/live",
    response_model=HealthEnvelope,
    summary="Liveness probe",
)
async def live() -> HealthEnvelope:
    """Returns 200 OK as long as the application process is running."""
    return HealthEnvelope(
        data=HealthStatus(version=settings.API_VERSION),
    )


@router.get(
    "/ready",
    response_model=HealthEnvelope,
    responses={
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "Dependencies degraded or unreachable",
        }
    },
    summary="Readiness probe",
)
async def ready(
    db: AsyncSession = Depends(get_db),
) -> HealthEnvelope:
    """Readiness probe returning 503 when downstream dependencies are degraded."""
    ok, unavailable = await _check_dependencies(db)
    if not ok:
        deps_str = ", ".join(unavailable)
        raise ApiError(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            code=ErrorCode.SERVICE_UNAVAILABLE,
            message=f"Unavailable dependencies: {deps_str}",
            headers={"Retry-After": "5"},
        )
    return HealthEnvelope(
        data=HealthStatus(version=settings.API_VERSION),
    )
