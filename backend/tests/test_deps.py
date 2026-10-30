"""Tests for authentication and authorization dependencies."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from fastapi.security import HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.deps import get_current_user, require_verified
from backend.core.errors import ApiError
from backend.core.security import create_access_token
from backend.models.user import User
from swarnbharat_shared.common import ErrorCode


async def test_get_current_user_success(db_session: AsyncSession) -> None:
    user_id = uuid4()
    email = f"testuser-{user_id}@example.com"
    user = User(
        id=user_id,
        email=email,
        full_name="Test User",
        is_verified=True,
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user_id)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    retrieved = await get_current_user(credentials=creds, db=db_session)
    assert retrieved.id == user_id
    assert retrieved.email == email

    verified_user = require_verified(retrieved)
    assert verified_user.id == user_id


async def test_get_current_user_unverified(db_session: AsyncSession) -> None:
    user_id = uuid4()
    email = f"unverified-{user_id}@example.com"
    user = User(
        id=user_id,
        email=email,
        full_name="Unverified User",
        is_verified=False,
    )
    db_session.add(user)
    await db_session.commit()

    token = create_access_token(user_id)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    retrieved = await get_current_user(credentials=creds, db=db_session)
    with pytest.raises(ApiError) as exc_info:
        require_verified(retrieved)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == ErrorCode.FORBIDDEN


async def test_get_current_user_missing_or_invalid_token(db_session: AsyncSession) -> None:
    # None credentials
    with pytest.raises(ApiError) as exc_none:
        await get_current_user(credentials=None, db=db_session)
    assert exc_none.value.status_code == 401
    assert exc_none.value.code == ErrorCode.UNAUTHORIZED

    # Invalid token string
    invalid_creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials="invalid.token")
    with pytest.raises(ApiError) as exc_invalid:
        await get_current_user(credentials=invalid_creds, db=db_session)
    assert exc_invalid.value.status_code == 401
    assert exc_invalid.value.code == ErrorCode.TOKEN_INVALID


async def test_get_current_user_expired_token(db_session: AsyncSession) -> None:
    user_id = uuid4()
    past = datetime.now(UTC) - timedelta(hours=1)
    payload = {
        "sub": str(user_id),
        "exp": past - timedelta(minutes=5),
        "iat": past - timedelta(minutes=10),
        "type": "access",
    }
    expired_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=expired_token)

    with pytest.raises(ApiError) as exc_expired:
        await get_current_user(credentials=creds, db=db_session)
    assert exc_expired.value.status_code == 401
    assert exc_expired.value.code == ErrorCode.TOKEN_EXPIRED


async def test_get_current_user_non_uuid_subject(db_session: AsyncSession) -> None:
    token = jwt.encode(
        {"sub": "not-a-uuid", "exp": datetime.now(UTC) + timedelta(minutes=5), "type": "access"},
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(ApiError) as exc_info:
        await get_current_user(credentials=creds, db=db_session)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == ErrorCode.TOKEN_INVALID


async def test_get_current_user_user_not_found(db_session: AsyncSession) -> None:
    nonexistent_id = uuid4()
    token = create_access_token(nonexistent_id)
    creds = HTTPAuthorizationCredentials(scheme="Bearer", credentials=token)
    with pytest.raises(ApiError) as exc_info:
        await get_current_user(credentials=creds, db=db_session)
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == ErrorCode.UNAUTHORIZED
