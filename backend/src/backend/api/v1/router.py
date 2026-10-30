"""V1 API router aggregating domain endpoints."""

from __future__ import annotations

from fastapi import APIRouter

from backend.api.v1.endpoints import health

v1_router = APIRouter()

v1_router.include_router(
    health.router,
    prefix="/health",
    tags=["Health"],
)
