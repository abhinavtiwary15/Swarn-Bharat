"""Auth request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    """User registration payload."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str = Field(min_length=1, max_length=200)


class LoginRequest(BaseModel):
    """User login payload."""

    email: EmailStr
    password: str


class RefreshRequest(BaseModel):
    """Refresh token payload."""

    refresh_token: str


class LogoutRequest(BaseModel):
    """Logout payload."""

    refresh_token: str


class GoogleTokenRequest(BaseModel):
    """Google ID token payload."""

    credential: str


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
    oauth_provider: str | None
    created_at: datetime
