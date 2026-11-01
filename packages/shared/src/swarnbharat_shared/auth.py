"""Auth request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field, field_validator

from swarnbharat_shared.common import LogoutEnvelope, LogoutStatus, SuccessEnvelope


class RegisterRequest(BaseModel):
    """User registration payload."""

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)

    @field_validator("full_name")
    @classmethod
    def _validate_full_name(cls, v: str) -> str:
        stripped = v.strip()
        if not (1 <= len(stripped) <= 200):
            raise ValueError("full_name must be between 1 and 200 characters after trimming")
        return stripped


class LoginRequest(BaseModel):
    """User login payload."""

    email: EmailStr = Field(max_length=254)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    """Refresh token payload."""

    refresh_token: str = Field(min_length=1, max_length=2048)


class LogoutRequest(BaseModel):
    """Logout payload."""

    refresh_token: str = Field(min_length=1, max_length=2048)


class TokenPair(BaseModel):
    """Access and refresh token pair."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105
    expires_in: int


class UserPublic(BaseModel):
    """Public user profile."""

    id: UUID
    email: EmailStr
    full_name: str
    is_verified: bool
    oauth_provider: str | None = None
    created_at: datetime


class UserEnvelope(SuccessEnvelope[UserPublic]):
    """Typed envelope for user profile responses."""


class TokenEnvelope(SuccessEnvelope[TokenPair]):
    """Typed envelope for token pair responses."""


__all__ = [
    "LoginRequest",
    "LogoutEnvelope",
    "LogoutRequest",
    "LogoutStatus",
    "RefreshRequest",
    "RegisterRequest",
    "TokenEnvelope",
    "TokenPair",
    "UserEnvelope",
    "UserPublic",
]
