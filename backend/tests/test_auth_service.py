"""Tests for auth_service business logic, throttling, and session lifecycle."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.errors import ApiError
from backend.core.redis import redis_throttle, redis_tokens
from backend.core.security import create_access_token
from backend.models.user import User
from backend.services import auth_service
from swarnbharat_shared.auth import RegisterRequest
from swarnbharat_shared.common import ErrorCode


@pytest.fixture(autouse=True)
async def cleanup_redis() -> AsyncIterator[None]:
    """Clean Redis DB 2 and DB 4 state between tests."""
    await redis_tokens.flushdb()
    await redis_throttle.flushdb()
    yield
    await redis_tokens.flushdb()
    await redis_throttle.flushdb()


@pytest.mark.asyncio
async def test_register_creates_user_and_hashes_password(db_session: AsyncSession) -> None:
    req = RegisterRequest(
        email="Alice@Example.COM",
        password="securePassword123",
        full_name="  Alice Wonderland  ",
    )
    user_public = await auth_service.register(db_session, req)
    assert user_public.email == "alice@example.com"
    assert user_public.full_name == "Alice Wonderland"
    assert user_public.is_verified is False
    assert user_public.oauth_provider is None


@pytest.mark.asyncio
async def test_register_duplicate_email_raises_email_taken(db_session: AsyncSession) -> None:
    req = RegisterRequest(
        email="bob@example.com",
        password="securePassword123",
        full_name="Bob Builder",
    )
    await auth_service.register(db_session, req)

    req_dup = RegisterRequest(
        email="BOB@example.com",
        password="anotherPassword456",
        full_name="Bob Another",
    )
    with pytest.raises(ApiError) as exc_info:
        await auth_service.register(db_session, req_dup)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == ErrorCode.EMAIL_TAKEN
    assert exc_info.value.field == "email"


@pytest.mark.asyncio
async def test_login_success_clears_throttle_counter(db_session: AsyncSession) -> None:
    req = RegisterRequest(
        email="carol@example.com",
        password="correctPassword123",
        full_name="Carol Danvers",
    )
    await auth_service.register(db_session, req)

    # Failed attempt first
    with pytest.raises(ApiError) as exc_info:
        await auth_service.login(
            db_session,
            "carol@example.com",
            "wrongPassword",
        )
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == ErrorCode.INVALID_CREDENTIALS

    # Verify throttle key exists in redis_throttle
    keys = await redis_throttle.keys("login:fail:*")
    assert len(keys) == 1

    # Successful login
    tokens = await auth_service.login(
        db_session,
        "carol@example.com",
        "correctPassword123",
    )
    assert tokens.access_token
    assert tokens.refresh_token
    assert tokens.expires_in == settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60

    # Throttle key deleted
    keys_after = await redis_throttle.keys("login:fail:*")
    assert len(keys_after) == 0


@pytest.mark.asyncio
async def test_login_lockout_after_max_attempts(db_session: AsyncSession) -> None:
    req = RegisterRequest(
        email="dave@example.com",
        password="correctPassword123",
        full_name="Dave Miller",
    )
    await auth_service.register(db_session, req)

    # Attempts 1..10 return 401
    for _ in range(10):
        with pytest.raises(ApiError) as exc_info:
            await auth_service.login(
                db_session,
                "dave@example.com",
                "wrongPassword",
            )
        assert exc_info.value.status_code == 401
        assert exc_info.value.code == ErrorCode.INVALID_CREDENTIALS

    # Attempt 11 returns 429 ACCOUNT_LOCKED, even with correct password
    with pytest.raises(ApiError) as exc_info:
        await auth_service.login(
            db_session,
            "dave@example.com",
            "correctPassword123",
        )
    assert exc_info.value.status_code == 429
    assert exc_info.value.code == ErrorCode.ACCOUNT_LOCKED
    headers = exc_info.value.headers or {}
    assert "Retry-After" in headers
    retry_after = int(headers["Retry-After"])
    assert 1 <= retry_after <= settings.LOGIN_LOCKOUT_SECONDS


@pytest.mark.asyncio
async def test_login_unknown_email_locks_out_identically(db_session: AsyncSession) -> None:
    unknown = "unknown@example.com"
    for _ in range(10):
        with pytest.raises(ApiError) as exc_info:
            await auth_service.login(
                db_session,
                unknown,
                "anyPassword",
            )
        assert exc_info.value.status_code == 401
        assert exc_info.value.code == ErrorCode.INVALID_CREDENTIALS

    with pytest.raises(ApiError) as exc_info:
        await auth_service.login(
            db_session,
            unknown,
            "anyPassword",
        )
    assert exc_info.value.status_code == 429
    assert exc_info.value.code == ErrorCode.ACCOUNT_LOCKED


@pytest.mark.asyncio
async def test_refresh_token_lifecycle(db_session: AsyncSession) -> None:
    req = RegisterRequest(
        email="eve@example.com",
        password="correctPassword123",
        full_name="Eve Adams",
    )
    await auth_service.register(db_session, req)
    tokens = await auth_service.login(
        db_session,
        "eve@example.com",
        "correctPassword123",
    )

    # Normal rotation
    new_tokens = await auth_service.refresh(db_session, tokens.refresh_token)
    assert new_tokens.refresh_token != tokens.refresh_token
    assert new_tokens.access_token

    # Replay within grace window succeeds and returns identical successor token
    grace_tokens = await auth_service.refresh(db_session, tokens.refresh_token)
    assert grace_tokens.refresh_token == new_tokens.refresh_token


@pytest.mark.asyncio
async def test_refresh_user_deleted_revokes_all_sessions(db_session: AsyncSession) -> None:
    req = RegisterRequest(
        email="frank@example.com",
        password="correctPassword123",
        full_name="Frank Castle",
    )
    user_pub = await auth_service.register(db_session, req)
    tokens = await auth_service.login(
        db_session,
        "frank@example.com",
        "correctPassword123",
    )

    # Delete user from DB
    user = await db_session.get(User, user_pub.id)
    assert user is not None
    await db_session.delete(user)
    await db_session.commit()

    # Refresh should detect missing user, revoke all sessions, and raise 401 UNAUTHORIZED
    with pytest.raises(ApiError) as exc_info:
        await auth_service.refresh(db_session, tokens.refresh_token)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED


@pytest.mark.asyncio
async def test_logout_idempotency_and_expired(db_session: AsyncSession) -> None:
    req = RegisterRequest(
        email="grace@example.com",
        password="correctPassword123",
        full_name="Grace Hopper",
    )
    user_pub = await auth_service.register(db_session, req)
    tokens = await auth_service.login(
        db_session,
        "grace@example.com",
        "correctPassword123",
    )

    # First logout succeeds
    res1 = await auth_service.logout(tokens.refresh_token)
    assert res1.status == "ok"

    # Second logout on same token also succeeds (idempotent)
    res2 = await auth_service.logout(tokens.refresh_token)
    assert res2.status == "ok"

    # Expired token logout also succeeds
    expired_payload: dict[str, Any] = {
        "sub": str(user_pub.id),
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(UTC) - timedelta(days=1),
        "iat": datetime.now(UTC) - timedelta(days=8),
        "type": "refresh",
    }
    expired_token = jwt.encode(
        expired_payload,
        settings.JWT_REFRESH_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    res_exp = await auth_service.logout(expired_token)
    assert res_exp.status == "ok"


@pytest.mark.asyncio
async def test_refresh_token_tampered_and_invalid_subject(db_session: AsyncSession) -> None:
    # Tampered signature
    with pytest.raises(ApiError) as exc_info:
        await auth_service.refresh(db_session, "invalid.jwt.token")
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == ErrorCode.TOKEN_INVALID

    # Non-UUID sub
    bad_sub_payload: dict[str, Any] = {
        "sub": "not-a-uuid",
        "jti": str(uuid.uuid4()),
        "exp": datetime.now(UTC) + timedelta(days=1),
        "iat": datetime.now(UTC),
        "type": "refresh",
    }
    bad_sub_token = jwt.encode(
        bad_sub_payload,
        settings.JWT_REFRESH_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(ApiError) as exc_info2:
        await auth_service.refresh(db_session, bad_sub_token)
    assert exc_info2.value.status_code == 401
    assert exc_info2.value.code == ErrorCode.TOKEN_INVALID


@pytest.mark.asyncio
async def test_access_token_cannot_be_used_as_refresh_token(db_session: AsyncSession) -> None:
    access_tok = create_access_token(uuid.uuid4())
    with pytest.raises(ApiError) as exc_info:
        await auth_service.refresh(db_session, access_tok)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == ErrorCode.TOKEN_INVALID
