"""Shared data contracts and Pydantic schemas."""

from swarnbharat_shared.auth import (
    GoogleTokenRequest,
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenPair,
    UserPublic,
)
from swarnbharat_shared.common import (
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    HealthEnvelope,
    HealthStatus,
    SuccessEnvelope,
)

__all__ = [
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "GoogleTokenRequest",
    "HealthEnvelope",
    "HealthStatus",
    "LoginRequest",
    "LogoutRequest",
    "RefreshRequest",
    "RegisterRequest",
    "SuccessEnvelope",
    "TokenPair",
    "UserPublic",
]
