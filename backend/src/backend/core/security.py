"""Security primitives for password hashing and JWT lifecycle."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

import anyio
import jwt
from anyio import CapacityLimiter
from pwdlib import PasswordHash
from pwdlib.hashers.argon2 import Argon2Hasher

from backend.core.config import settings

_password_hash = PasswordHash((Argon2Hasher(),))
_DUMMY_HASH = _password_hash.hash("swarnbharat-dummy-timing-defense")

_password_limiter = CapacityLimiter(4)

_PROTECTED_CLAIMS = frozenset({"sub", "exp", "iat", "jti", "type"})


async def hash_password(password: str) -> str:
    """Hash a plaintext password using Argon2id off the event loop thread."""
    return await anyio.to_thread.run_sync(_password_hash.hash, password, limiter=_password_limiter)


async def verify_password(plain_password: str, hashed_password: str | None) -> bool:
    """Verify password against hash off the event loop thread; runs dummy verify if None."""
    if hashed_password is None:
        await anyio.to_thread.run_sync(
            _password_hash.verify, plain_password, _DUMMY_HASH, limiter=_password_limiter
        )
        return False
    return await anyio.to_thread.run_sync(
        _password_hash.verify, plain_password, hashed_password, limiter=_password_limiter
    )


def create_access_token(
    subject: str | UUID,
    extra_claims: dict[str, Any] | None = None,
) -> str:
    """Create a signed JWT access token with standard expiration."""
    sub = str(subject)
    now = datetime.now(UTC)
    exp = now + timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)

    if extra_claims:
        overlap = _PROTECTED_CLAIMS.intersection(extra_claims.keys())
        if overlap:
            msg = f"Cannot override protected JWT claim(s): {', '.join(sorted(overlap))}"
            raise ValueError(msg)

    payload: dict[str, Any] = {
        "sub": sub,
        "exp": exp,
        "iat": now,
        "type": "access",
    }
    if extra_claims:
        payload.update(extra_claims)

    return jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_refresh_token(
    subject: str | UUID,
    jti: str | None = None,
) -> tuple[str, str]:
    """Create a signed JWT refresh token and return (token, jti).

    Note: Redis state is authoritative for validity; the JWT exp claim is advisory.
    """
    sub = str(subject)
    token_jti = jti or str(uuid4())
    now = datetime.now(UTC)
    exp = now + timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)

    payload: dict[str, Any] = {
        "sub": sub,
        "exp": exp,
        "iat": now,
        "jti": token_jti,
        "type": "refresh",
    }
    token = jwt.encode(payload, settings.JWT_REFRESH_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, token_jti


def _decode(
    token: str,
    secret_key: str,
    expected_kind: str,
    required_claims: list[str],
) -> dict[str, Any]:
    """Decode and validate a JWT, ensuring required claims and token type match."""
    payload: dict[str, Any] = jwt.decode(
        token,
        secret_key,
        algorithms=[settings.JWT_ALGORITHM],
        options={"require": required_claims},
    )
    kind = payload.get("type")
    if kind != expected_kind:
        raise jwt.InvalidTokenError(f"Expected token type {expected_kind!r}, got {kind!r}")
    return payload


def decode_access_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT access token, enforcing required claims and type."""
    return _decode(
        token=token,
        secret_key=settings.JWT_SECRET_KEY,
        expected_kind="access",
        required_claims=["exp", "sub", "type"],
    )


def decode_refresh_token(token: str) -> dict[str, Any]:
    """Decode and validate a JWT refresh token, enforcing required claims, type, and jti."""
    return _decode(
        token=token,
        secret_key=settings.JWT_REFRESH_SECRET_KEY,
        expected_kind="refresh",
        required_claims=["exp", "sub", "type", "jti"],
    )
