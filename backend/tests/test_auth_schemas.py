"""Unit tests for auth request/response schemas and envelopes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from swarnbharat_shared.auth import (
    LoginRequest,
    LogoutEnvelope,
    LogoutRequest,
    LogoutStatus,
    RefreshRequest,
    RegisterRequest,
    TokenEnvelope,
    TokenPair,
    UserEnvelope,
    UserPublic,
)


def test_register_request_valid() -> None:
    req = RegisterRequest(
        email="user@example.com",
        password="securePassword123",
        full_name="  Jane Doe  ",
    )
    assert req.email == "user@example.com"
    assert req.password == "securePassword123"
    assert req.full_name == "Jane Doe"


def test_register_request_invalid_whitespace_name() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="user@example.com",
            password="securePassword123",
            full_name="   ",
        )


def test_register_request_invalid_name_too_long() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="user@example.com",
            password="securePassword123",
            full_name="a" * 201,
        )


def test_register_request_short_password() -> None:
    with pytest.raises(ValidationError):
        RegisterRequest(
            email="user@example.com",
            password="short",
            full_name="Jane Doe",
        )


def test_login_request_valid() -> None:
    req = LoginRequest(email="user@example.com", password="password")
    assert req.email == "user@example.com"
    assert req.password == "password"


def test_login_request_empty_password() -> None:
    with pytest.raises(ValidationError):
        LoginRequest(email="user@example.com", password="")


def test_token_requests_bound() -> None:
    req_refresh = RefreshRequest(refresh_token="t" * 2048)
    assert len(req_refresh.refresh_token) == 2048

    with pytest.raises(ValidationError):
        RefreshRequest(refresh_token="t" * 2049)

    req_logout = LogoutRequest(refresh_token="t" * 2048)
    assert len(req_logout.refresh_token) == 2048

    with pytest.raises(ValidationError):
        LogoutRequest(refresh_token="t" * 2049)


def test_concrete_envelopes() -> None:
    user = UserPublic(
        id=uuid.uuid4(),
        email="test@example.com",
        full_name="Test User",
        is_verified=False,
        created_at=datetime.now(UTC),
    )
    user_env = UserEnvelope(data=user)
    assert user_env.success is True
    assert user_env.data.email == "test@example.com"
    assert user_env.error is None

    tokens = TokenPair(
        access_token="acc",
        refresh_token="ref",
        token_type="bearer",
        expires_in=900,
    )
    tok_env = TokenEnvelope(data=tokens)
    assert tok_env.success is True
    assert tok_env.data.access_token == "acc"

    logout_env = LogoutEnvelope(data=LogoutStatus())
    assert logout_env.success is True
    assert logout_env.data.status == "ok"
