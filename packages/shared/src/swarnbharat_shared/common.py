"""Common response envelope and utility schemas."""

from __future__ import annotations

from enum import StrEnum
from typing import Generic, Literal, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class ErrorCode(StrEnum):
    """Machine-readable error codes used across the API."""

    BAD_REQUEST = "BAD_REQUEST"
    UNAUTHORIZED = "UNAUTHORIZED"
    FORBIDDEN = "FORBIDDEN"
    NOT_FOUND = "NOT_FOUND"
    METHOD_NOT_ALLOWED = "METHOD_NOT_ALLOWED"
    CONFLICT = "CONFLICT"
    VALIDATION_ERROR = "VALIDATION_ERROR"
    RATE_LIMIT_EXCEEDED = "RATE_LIMIT_EXCEEDED"
    INTERNAL_SERVER_ERROR = "INTERNAL_SERVER_ERROR"
    SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE"
    RATE_LIMITER_UNAVAILABLE = "RATE_LIMITER_UNAVAILABLE"
    HTTP_ERROR = "HTTP_ERROR"


class ErrorDetail(BaseModel):
    """Machine-readable error detail included in error envelopes."""

    code: str
    message: str
    field: str | None = None


class ApiResponse(BaseModel, Generic[T]):
    """Standard response envelope returned by API endpoints."""

    success: bool
    data: T | None = None
    error: ErrorDetail | None = None


class ErrorResponse(BaseModel):
    """Concrete non-2xx response envelope."""

    success: Literal[False] = False
    data: None = None
    error: ErrorDetail


class MessageResponse(BaseModel):
    """Single-string status response."""

    message: str


class HealthStatus(BaseModel):
    """Health check dependency status."""

    status: str
    version: str
    db_ok: bool
    redis_ok: bool


class HealthEnvelope(ApiResponse[HealthStatus]):
    """Typed envelope for health check endpoints."""

    data: HealthStatus | None = None
