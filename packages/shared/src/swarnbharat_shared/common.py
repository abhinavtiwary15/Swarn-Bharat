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
    TOKEN_EXPIRED = "TOKEN_EXPIRED"  # noqa: S105
    TOKEN_INVALID = "TOKEN_INVALID"  # noqa: S105
    HTTP_ERROR = "HTTP_ERROR"


class ErrorDetail(BaseModel):
    """Machine-readable error detail included in error envelopes."""

    code: ErrorCode
    message: str
    field: str | None = None


class ErrorResponse(BaseModel):
    """Concrete non-2xx response envelope."""

    success: Literal[False] = False
    data: None = None
    error: ErrorDetail


class SuccessEnvelope(BaseModel, Generic[T]):
    """Standard success response envelope."""

    success: Literal[True] = True
    data: T
    error: None = None


class HealthStatus(BaseModel):
    """Health check dependency status."""

    status: Literal["ok"] = "ok"
    version: str


class HealthEnvelope(SuccessEnvelope[HealthStatus]):
    """Typed envelope for health check responses."""
