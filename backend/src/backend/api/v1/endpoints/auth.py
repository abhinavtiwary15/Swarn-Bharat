"""Authentication endpoints for user registration, sessions, and credentials."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.database import get_db
from backend.core.deps import get_current_user
from backend.core.rate_limit import fixed_window
from backend.models.user import User
from backend.services import auth_service
from swarnbharat_shared.auth import (
    LoginRequest,
    LogoutEnvelope,
    LogoutRequest,
    RefreshRequest,
    RegisterRequest,
    TokenEnvelope,
    UserEnvelope,
)
from swarnbharat_shared.common import ErrorResponse

router = APIRouter()

_RATE_LIMIT_503_RESPONSES: dict[int | str, dict[str, Any]] = {
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "model": ErrorResponse,
        "description": "Rate limit exceeded or account locked",
        "headers": {
            "Retry-After": {
                "schema": {"type": "integer"},
                "description": "Seconds to wait before retrying",
            }
        },
    },
    status.HTTP_503_SERVICE_UNAVAILABLE: {
        "model": ErrorResponse,
        "description": (
            "Downstream service or rate limiter unavailable "
            "(SERVICE_UNAVAILABLE or RATE_LIMITER_UNAVAILABLE)"
        ),
        "headers": {
            "Retry-After": {
                "schema": {"type": "integer"},
                "description": "Seconds to wait before retrying",
            }
        },
    },
}


@router.post(
    "/register",
    status_code=status.HTTP_201_CREATED,
    response_model=UserEnvelope,
    dependencies=[
        Depends(
            fixed_window(
                times=settings.REGISTER_RATE_LIMIT_TIMES,
                seconds=settings.REGISTER_RATE_LIMIT_SECONDS,
            )
        )
    ],
    responses={
        status.HTTP_409_CONFLICT: {
            "model": ErrorResponse,
            "description": "Email already registered (EMAIL_TAKEN)",
        },
        422: {
            "model": ErrorResponse,
            "description": "Validation error (VALIDATION_ERROR)",
        },
        **_RATE_LIMIT_503_RESPONSES,
    },
    summary="Register user account",
)
async def register(
    payload: RegisterRequest,
    db: AsyncSession = Depends(get_db),
) -> UserEnvelope:
    """Register a new user account with normalized email and trimmed full name."""
    user = await auth_service.register(db, payload)
    return UserEnvelope(data=user)


@router.post(
    "/login",
    status_code=status.HTTP_200_OK,
    response_model=TokenEnvelope,
    dependencies=[
        Depends(
            fixed_window(
                times=settings.LOGIN_RATE_LIMIT_TIMES,
                seconds=settings.LOGIN_RATE_LIMIT_SECONDS,
            )
        )
    ],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Invalid credentials (INVALID_CREDENTIALS)",
        },
        422: {
            "model": ErrorResponse,
            "description": "Validation error (VALIDATION_ERROR)",
        },
        **_RATE_LIMIT_503_RESPONSES,
    },
    summary="Log in user",
)
async def login(
    payload: LoginRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenEnvelope:
    """Authenticate credentials with fixed-window lockout and anti-timing defense."""
    tokens = await auth_service.login(db, payload.email, payload.password)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return TokenEnvelope(data=tokens)


@router.post(
    "/refresh",
    status_code=status.HTTP_200_OK,
    response_model=TokenEnvelope,
    dependencies=[
        Depends(
            fixed_window(
                times=settings.REFRESH_RATE_LIMIT_TIMES,
                seconds=settings.REFRESH_RATE_LIMIT_SECONDS,
            )
        )
    ],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Token expired, invalid, session revoked, or reuse detected",
        },
        422: {
            "model": ErrorResponse,
            "description": "Validation error (VALIDATION_ERROR)",
        },
        **_RATE_LIMIT_503_RESPONSES,
    },
    summary="Refresh access and refresh tokens",
)
async def refresh(
    payload: RefreshRequest,
    response: Response,
    db: AsyncSession = Depends(get_db),
) -> TokenEnvelope:
    """Rotate single-use refresh token with grace window reuse detection."""
    tokens = await auth_service.refresh(db, payload.refresh_token)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Pragma"] = "no-cache"
    return TokenEnvelope(data=tokens)


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    response_model=LogoutEnvelope,
    dependencies=[
        Depends(
            fixed_window(
                times=settings.LOGOUT_RATE_LIMIT_TIMES,
                seconds=settings.LOGOUT_RATE_LIMIT_SECONDS,
            )
        )
    ],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Token invalid (TOKEN_INVALID)",
        },
        422: {
            "model": ErrorResponse,
            "description": "Validation error (VALIDATION_ERROR)",
        },
        **_RATE_LIMIT_503_RESPONSES,
    },
    summary="Log out user",
)
async def logout(
    payload: LogoutRequest,
) -> LogoutEnvelope:
    """Idempotently revoke the presented refresh token session."""
    status_payload = await auth_service.logout(payload.refresh_token)
    return LogoutEnvelope(data=status_payload)


@router.get(
    "/me",
    status_code=status.HTTP_200_OK,
    response_model=UserEnvelope,
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorResponse,
            "description": "Unauthorized, token expired, or token invalid",
        },
        status.HTTP_503_SERVICE_UNAVAILABLE: {
            "model": ErrorResponse,
            "description": "Database outage (SERVICE_UNAVAILABLE)",
            "headers": {
                "Retry-After": {
                    "schema": {"type": "integer"},
                    "description": "Seconds to wait before retrying",
                }
            },
        },
    },
    summary="Get current user profile",
)
async def me(
    user: User = Depends(get_current_user),
) -> UserEnvelope:
    """Return the profile for the currently authenticated Bearer token user."""
    return UserEnvelope(data=auth_service._to_user_public(user))
