"""FastAPI authentication and authorization dependencies."""

from __future__ import annotations

from uuid import UUID

import jwt
from fastapi import Depends, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.errors import ApiError
from backend.core.security import decode_access_token
from backend.models.user import User
from swarnbharat_shared.common import ErrorCode

http_bearer = HTTPBearer(auto_error=False)


def _unauthorized(
    code: ErrorCode = ErrorCode.UNAUTHORIZED,
    message: str = "Not authenticated",
    authenticate_header: str = "Bearer",
) -> ApiError:
    return ApiError(
        status_code=status.HTTP_401_UNAUTHORIZED,
        code=code,
        message=message,
        headers={"WWW-Authenticate": authenticate_header},
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(http_bearer),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Extract, decode, and validate the Bearer access token, returning the user entity."""
    if credentials is None or not credentials.credentials:
        raise _unauthorized(ErrorCode.UNAUTHORIZED, "Not authenticated")

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorized(
            ErrorCode.TOKEN_EXPIRED,
            "Access token has expired",
            'Bearer error="invalid_token", error_description="Token expired"',
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise _unauthorized(
            ErrorCode.TOKEN_INVALID,
            "Invalid access token",
            'Bearer error="invalid_token"',
        ) from exc

    sub = payload.get("sub")
    if not sub:
        raise _unauthorized(
            ErrorCode.TOKEN_INVALID,
            "Token subject missing",
            'Bearer error="invalid_token"',
        )

    try:
        user_id = UUID(sub)
    except (ValueError, TypeError) as exc:
        raise _unauthorized(
            ErrorCode.TOKEN_INVALID,
            "Invalid user ID in token subject",
            'Bearer error="invalid_token"',
        ) from exc

    user = await db.get(User, user_id)
    if not user:
        raise _unauthorized(ErrorCode.UNAUTHORIZED, "User not found")

    return user


def require_verified(
    user: User = Depends(get_current_user),
) -> User:
    """Ensure the authenticated user has verified their email address."""
    if not user.is_verified:
        raise ApiError(
            status_code=status.HTTP_403_FORBIDDEN,
            code=ErrorCode.FORBIDDEN,
            message="Email verification required",
        )
    return user
