"""Integration tests for HTTP authentication endpoints."""

from __future__ import annotations

import httpx
import pytest

from backend.core.redis import redis_throttle, redis_tokens


@pytest.fixture(autouse=True)
async def cleanup_test_redis() -> None:
    await redis_tokens.flushdb()
    await redis_throttle.flushdb()


@pytest.mark.asyncio
async def test_register_flow(client: httpx.AsyncClient) -> None:
    payload = {
        "email": "User1@Example.com",
        "password": "securePassword123",
        "full_name": "  Test User One  ",
    }
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert body["success"] is True
    assert body["data"]["email"] == "user1@example.com"
    assert body["data"]["full_name"] == "Test User One"
    assert body["data"]["is_verified"] is False
    assert body["data"]["oauth_provider"] is None
    assert "id" in body["data"]

    # Duplicate registration returns 409 EMAIL_TAKEN
    r_dup = await client.post("/api/v1/auth/register", json=payload)
    assert r_dup.status_code == 409
    body_dup = r_dup.json()
    assert body_dup["success"] is False
    assert body_dup["error"]["code"] == "EMAIL_TAKEN"
    assert body_dup["error"]["field"] == "email"


@pytest.mark.asyncio
async def test_register_validation_error(client: httpx.AsyncClient) -> None:
    payload = {
        "email": "not-an-email",
        "password": "short",
        "full_name": "   ",
    }
    r = await client.post("/api/v1/auth/register", json=payload)
    assert r.status_code == 422
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


@pytest.mark.asyncio
async def test_login_success_and_headers(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "user2@example.com",
            "password": "password123",
            "full_name": "User Two",
        },
    )

    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "USER2@example.com", "password": "password123"},
    )
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
    assert r.headers.get("pragma") == "no-cache"
    body = r.json()
    assert body["success"] is True
    data = body["data"]
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 900


@pytest.mark.asyncio
async def test_login_invalid_credentials(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "wrongPassword"},
    )
    assert r.status_code == 401
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_refresh_flow_and_no_www_authenticate(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "user3@example.com",
            "password": "password123",
            "full_name": "User Three",
        },
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "user3@example.com", "password": "password123"},
    )
    tokens = login_resp.json()["data"]

    # Refresh
    r = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert r.status_code == 200
    assert r.headers.get("cache-control") == "no-store"
    assert r.headers.get("pragma") == "no-cache"
    assert "access_token" in r.json()["data"]

    # Invalid refresh token -> 401 without WWW-Authenticate
    r_inv = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid.jwt.token"},
    )
    assert r_inv.status_code == 401
    assert "www-authenticate" not in r_inv.headers
    assert r_inv.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.asyncio
async def test_logout_and_subsequent_refresh(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "user4@example.com",
            "password": "password123",
            "full_name": "User Four",
        },
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "user4@example.com", "password": "password123"},
    )
    tokens = login_resp.json()["data"]

    # Logout
    r_logout = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert r_logout.status_code == 200
    assert r_logout.json()["data"]["status"] == "ok"

    # Subsequent refresh with revoked token returns 401 SESSION_REVOKED
    r_ref = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert r_ref.status_code == 401
    assert r_ref.json()["error"]["code"] == "SESSION_REVOKED"


@pytest.mark.asyncio
async def test_me_endpoint_with_auth_header(client: httpx.AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={
            "email": "user5@example.com",
            "password": "password123",
            "full_name": "User Five",
        },
    )
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "user5@example.com", "password": "password123"},
    )
    access_tok = login_resp.json()["data"]["access_token"]

    # GET /auth/me with Bearer token
    r = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_tok}"},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["data"]["email"] == "user5@example.com"

    # GET /auth/me without header returns 401 with WWW-Authenticate
    r_unauth = await client.get("/api/v1/auth/me")
    assert r_unauth.status_code == 401
    assert "www-authenticate" in r_unauth.headers
    assert r_unauth.headers["www-authenticate"].startswith("Bearer")
