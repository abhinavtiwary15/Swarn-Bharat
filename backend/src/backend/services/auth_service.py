"""Authentication business logic and credential management service."""

from __future__ import annotations

import hashlib
import logging
import uuid

import jwt
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.errors import ApiError
from backend.core.redis import redis_throttle as default_redis_throttle
from backend.core.security import (
    create_access_token,
    create_refresh_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)
from backend.models.user import User
from backend.services.token_service import (
    TokenNotFoundError,
    TokenReuseError,
    record_issued_token,
    revoke_all_for_user,
    revoke_token,
    rotate_token,
)
from swarnbharat_shared.auth import (
    LogoutStatus,
    RegisterRequest,
    TokenPair,
    UserPublic,
)
from swarnbharat_shared.common import ErrorCode

logger = logging.getLogger(__name__)


def normalize_email(email: str) -> str:
    """Strip surrounding whitespace and lowercase an email address."""
    return email.strip().lower()


def _to_user_public(user: User) -> UserPublic:
    return UserPublic(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        is_verified=user.is_verified,
        oauth_provider=user.oauth_provider,
        created_at=user.created_at,
    )


async def register(db: AsyncSession, payload: RegisterRequest) -> UserPublic:
    """Register a new user account with hashed password and normalized email."""
    norm_email = normalize_email(payload.email)
    trimmed_name = payload.full_name.strip()
    hashed = await hash_password(payload.password)

    user = User(
        email=norm_email,
        hashed_password=hashed,
        full_name=trimmed_name,
        is_verified=False,
        oauth_provider=None,
        oauth_sub=None,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        sqlstate = getattr(exc.orig, "sqlstate", None) or getattr(exc, "sqlstate", None)
        if sqlstate == "23505":
            raise ApiError(
                status_code=409,
                code=ErrorCode.EMAIL_TAKEN,
                message="An account with this email already exists",
                field="email",
            ) from exc
        if sqlstate == "23514":
            raise ApiError(
                status_code=422,
                code=ErrorCode.VALIDATION_ERROR,
                message="Email must be lowercase",
                field="email",
            ) from exc
        raise

    await db.refresh(user)
    return _to_user_public(user)


async def login(
    db: AsyncSession,
    email: str,
    password: str,
    redis_throttle: Redis = default_redis_throttle,
) -> TokenPair:
    """Authenticate credentials against DB with fixed-window lockout in Redis DB 4."""
    norm_email = normalize_email(email)
    email_hash = hashlib.sha256(norm_email.encode("utf-8")).hexdigest()
    throttle_key = f"login:fail:{email_hash}"

    async with redis_throttle.pipeline(transaction=True) as pipe:
        pipe.incr(throttle_key)
        pipe.expire(throttle_key, settings.LOGIN_LOCKOUT_SECONDS, nx=True)
        pipe.ttl(throttle_key)
        results = await pipe.execute()

    attempts: int = results[0]
    raw_ttl: int = results[2]
    ttl: int = max(raw_ttl, 1)

    if attempts > settings.MAX_LOGIN_ATTEMPTS:
        raise ApiError(
            status_code=429,
            code=ErrorCode.ACCOUNT_LOCKED,
            message=f"Too many failed login attempts. Try again in {ttl} seconds.",
            headers={"Retry-After": str(ttl)},
        )

    stmt = select(User).where(User.email == norm_email)
    result = await db.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or user.hashed_password is None:
        await verify_password(password, None)
        raise ApiError(
            status_code=401,
            code=ErrorCode.INVALID_CREDENTIALS,
            message="Invalid email or password",
        )

    valid = await verify_password(password, user.hashed_password)
    if not valid:
        raise ApiError(
            status_code=401,
            code=ErrorCode.INVALID_CREDENTIALS,
            message="Invalid email or password",
        )

    await redis_throttle.delete(throttle_key)

    access_token = create_access_token(user.id)
    refresh_token, jti = create_refresh_token(user.id)
    await record_issued_token(user.id, jti)

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def refresh(
    db: AsyncSession,
    refresh_token_str: str,
) -> TokenPair:
    """Rotate a refresh token, issuing a new token pair."""
    try:
        payload = decode_refresh_token(refresh_token_str)
    except jwt.ExpiredSignatureError as exc:
        raise ApiError(
            status_code=401,
            code=ErrorCode.TOKEN_EXPIRED,
            message="Refresh token has expired",
        ) from exc
    except jwt.InvalidTokenError as exc:
        raise ApiError(
            status_code=401,
            code=ErrorCode.TOKEN_INVALID,
            message="Invalid refresh token",
        ) from exc

    sub = payload.get("sub", "")
    try:
        user_id = uuid.UUID(sub)
    except (ValueError, TypeError) as exc:
        raise ApiError(
            status_code=401,
            code=ErrorCode.TOKEN_INVALID,
            message="Invalid token subject",
        ) from exc

    jti = payload.get("jti")
    if not jti:
        raise ApiError(
            status_code=401,
            code=ErrorCode.TOKEN_INVALID,
            message="Missing token identifier",
        )

    user = await db.get(User, user_id)
    if user is None:
        await revoke_all_for_user(user_id)
        raise ApiError(
            status_code=401,
            code=ErrorCode.UNAUTHORIZED,
            message="User not found",
        )

    new_jti = str(uuid.uuid4())
    try:
        rotation_res = await rotate_token(user_id, old_jti=jti, new_jti=new_jti)
    except TokenNotFoundError as exc:
        raise ApiError(
            status_code=401,
            code=ErrorCode.SESSION_REVOKED,
            message="Session has been revoked",
        ) from exc
    except TokenReuseError as exc:
        raise ApiError(
            status_code=401,
            code=ErrorCode.TOKEN_REUSE_DETECTED,
            message="Token reuse detected; all sessions revoked",
        ) from exc

    new_access = create_access_token(user.id)
    new_refresh, _ = create_refresh_token(user.id, jti=rotation_res.jti)

    return TokenPair(
        access_token=new_access,
        refresh_token=new_refresh,
        expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


async def logout(
    refresh_token_str: str,
) -> LogoutStatus:
    """Revoke a single refresh token session idempotently."""
    try:
        payload = decode_refresh_token(refresh_token_str)
    except jwt.ExpiredSignatureError:
        return LogoutStatus(status="ok")
    except jwt.InvalidTokenError as exc:
        raise ApiError(
            status_code=401,
            code=ErrorCode.TOKEN_INVALID,
            message="Invalid refresh token",
        ) from exc

    sub = payload.get("sub", "")
    try:
        user_id = uuid.UUID(sub)
    except (ValueError, TypeError) as exc:
        raise ApiError(
            status_code=401,
            code=ErrorCode.TOKEN_INVALID,
            message="Invalid token subject",
        ) from exc

    jti = payload.get("jti")
    if not jti:
        raise ApiError(
            status_code=401,
            code=ErrorCode.TOKEN_INVALID,
            message="Missing token identifier",
        )

    await revoke_token(user_id, jti)
    return LogoutStatus(status="ok")
