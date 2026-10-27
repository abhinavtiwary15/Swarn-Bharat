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
    ApiResponse,
    ErrorCode,
    ErrorDetail,
    ErrorResponse,
    HealthEnvelope,
    HealthStatus,
    MessageResponse,
)

__all__ = [
    "ApiResponse",
    "ErrorCode",
    "ErrorDetail",
    "ErrorResponse",
    "GoogleTokenRequest",
    "HealthEnvelope",
    "HealthStatus",
    "LoginRequest",
    "LogoutRequest",
    "MessageResponse",
    "RefreshRequest",
    "RegisterRequest",
    "TokenPair",
    "UserPublic",
]
