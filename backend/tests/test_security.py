"""Tests for password hashing, Argon2id concurrency limiter, and JWT lifecycle."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest

import backend.core.security as sec_mod
from backend.core.config import settings
from backend.core.security import (
    _password_limiter,
    create_access_token,
    create_refresh_token,
    decode_access_token,
    decode_refresh_token,
    hash_password,
    verify_password,
)


async def test_password_hash_and_verify() -> None:
    raw = "super-secret-password-123"
    hashed = await hash_password(raw)
    assert hashed != raw
    assert await verify_password(raw, hashed) is True
    assert await verify_password("wrong-password", hashed) is False


async def test_password_verify_dummy_defense_on_none() -> None:
    assert await verify_password("any-password", None) is False


async def test_password_limiter_bounds_concurrency(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _password_limiter.total_tokens == 4

    active_concurrent = 0
    max_observed_concurrent = 0
    lock = threading.Lock()

    def slow_hash(secret: str) -> str:
        nonlocal active_concurrent, max_observed_concurrent
        with lock:
            active_concurrent += 1
            if active_concurrent > max_observed_concurrent:
                max_observed_concurrent = active_concurrent
        time.sleep(0.05)
        with lock:
            active_concurrent -= 1
        return f"mock-hash-{secret}"

    monkeypatch.setattr(sec_mod._password_hash, "hash", slow_hash)

    tasks = [hash_password(f"pwd-{i}") for i in range(10)]
    results = await asyncio.gather(*tasks)

    assert len(results) == 10
    assert max_observed_concurrent <= 4


def test_access_token_creation_and_decode() -> None:
    user_id = uuid4()
    token = create_access_token(user_id)
    payload = decode_access_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["type"] == "access"
    assert "exp" in payload
    assert "iat" in payload


def test_access_token_extra_claims() -> None:
    user_id = uuid4()
    token = create_access_token(user_id, extra_claims={"role": "admin", "custom": "val"})
    payload = decode_access_token(token)
    assert payload["role"] == "admin"
    assert payload["custom"] == "val"


def test_access_token_protected_claim_override_rejected() -> None:
    user_id = uuid4()
    for protected in ("sub", "exp", "iat", "jti", "type"):
        with pytest.raises(ValueError, match="Cannot override protected JWT claim"):
            create_access_token(user_id, extra_claims={protected: "hacked"})


def test_refresh_token_creation_and_decode() -> None:
    user_id = uuid4()
    token, jti = create_refresh_token(user_id)
    payload = decode_refresh_token(token)
    assert payload["sub"] == str(user_id)
    assert payload["jti"] == jti
    assert payload["type"] == "refresh"


def test_decode_token_wrong_type_rejected() -> None:
    user_id = uuid4()
    # 1. Access token passed to decode_refresh_token fails due to separate signing secret
    access_token = create_access_token(user_id)
    with pytest.raises(jwt.InvalidTokenError):
        decode_refresh_token(access_token)

    # 2. Token signed with refresh key but asserting type 'access'
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(minutes=5),
        "iat": datetime.now(UTC),
        "jti": str(uuid4()),
        "type": "access",
    }
    forged_refresh = jwt.encode(
        payload, settings.JWT_REFRESH_SECRET_KEY, algorithm=settings.JWT_ALGORITHM
    )
    with pytest.raises(jwt.InvalidTokenError, match="Expected token type 'refresh'"):
        decode_refresh_token(forged_refresh)

    # 3. Token signed with access key but asserting type 'refresh'
    payload["type"] = "refresh"
    forged_access = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(jwt.InvalidTokenError, match="Expected token type 'access'"):
        decode_access_token(forged_access)


def test_decode_token_expired_rejected() -> None:
    user_id = uuid4()
    past = datetime.now(UTC) - timedelta(hours=1)
    payload = {
        "sub": str(user_id),
        "exp": past - timedelta(minutes=5),
        "iat": past - timedelta(minutes=10),
        "type": "access",
    }
    expired_token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired_token)


def test_decode_token_without_exp_rejected() -> None:
    user_id = uuid4()
    payload = {
        "sub": str(user_id),
        "type": "access",
    }
    token_without_exp = jwt.encode(
        payload,
        settings.JWT_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_access_token(token_without_exp)


def test_decode_refresh_token_without_jti_rejected() -> None:
    user_id = uuid4()
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(days=7),
        "iat": datetime.now(UTC),
        "type": "refresh",
    }
    token_without_jti = jwt.encode(
        payload,
        settings.JWT_REFRESH_SECRET_KEY,
        algorithm=settings.JWT_ALGORITHM,
    )
    with pytest.raises(jwt.MissingRequiredClaimError):
        decode_refresh_token(token_without_jti)
