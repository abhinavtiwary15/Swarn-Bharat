"""Integration tests for POST /api/v1/auth/refresh.

Spec reference: docs/specs/auth-b2.md §6 and openapi.json.
"""

from __future__ import annotations

import asyncio
import typing
from uuid import uuid4

import httpx
import pytest
import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession

CORS_ORIGIN = "http://localhost:3000"


@pytest.mark.asyncio
async def test_refresh_success_and_headers(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §6:
    '200 | none | New token pair (same shape and headers as login). Also returned for a replay inside the grace window.'
    and:
    'There is no 404 on this endpoint. 401 responses carry no WWW-Authenticate header because the token travels in the body.'
    """
    email = "refresh_success@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Refresh User"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    tokens = login_res.json()["data"]
    r1 = tokens["refresh_token"]

    ref_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert ref_res.status_code == 200
    assert ref_res.headers.get("cache-control") == "no-store"
    assert ref_res.headers.get("pragma") == "no-cache"
    assert "www-authenticate" not in ref_res.headers

    body = ref_res.json()
    assert body["success"] is True
    assert body["error"] is None
    data = body["data"]
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 900
    assert data["refresh_token"] != r1


@pytest.mark.asyncio
async def test_refresh_grace_window_replay_returns_same_successor(
    client: httpx.AsyncClient,
) -> None:
    """Spec: docs/specs/auth-b2.md §3:
    'Grace window: presenting a refresh token again within the grace window after it was rotated succeeds and returns a refresh token carrying the same jti as the first successor. No second session is created.'
    """
    email = "grace_replay@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Grace User"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    r1 = login_res.json()["data"]["refresh_token"]

    # First rotation: r1 -> r2
    rotate_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert rotate_res.status_code == 200
    r2_data = rotate_res.json()["data"]

    # Replay r1 within grace window (default 30s)
    replay_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert replay_res.status_code == 200
    replay_data = replay_res.json()["data"]

    assert replay_data["refresh_token"] == r2_data["refresh_token"]
    assert replay_data["access_token"] == r2_data["access_token"]


@pytest.mark.asyncio
async def test_refresh_concurrent_same_token_returns_identical_successor(
    client: httpx.AsyncClient,
) -> None:
    """Spec: docs/specs/auth-b2.md §3:
    'Grace window: presenting a refresh token again within the grace window after it was rotated succeeds and returns a refresh token carrying the same jti as the first successor. No second session is created.'
    """
    import jwt

    email = "concurrent_refresh@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Concurrent User"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    r1 = login_res.json()["data"]["refresh_token"]

    responses = await asyncio.gather(
        *[client.post("/api/v1/auth/refresh", json={"refresh_token": r1}) for _ in range(5)]
    )

    assert all(r.status_code == 200 for r in responses)
    payloads = [r.json()["data"] for r in responses]

    # All returned refresh tokens carry the same replacement jti
    jtis = [
        jwt.decode(p["refresh_token"], options={"verify_signature": False})["jti"] for p in payloads
    ]
    assert len(set(jtis)) == 1


@pytest.mark.asyncio
async def test_refresh_reuse_after_grace_window_revokes_all_sessions(
    client: httpx.AsyncClient,
    app_settings: typing.Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Spec: docs/specs/auth-b2.md §3:
    'Reuse: presenting a rotated refresh token after the grace window is a replay. The response is 401 TOKEN_REUSE_DETECTED and every refresh token of that user becomes invalid; afterwards each of them yields 401 SESSION_REVOKED.'
    and §6:
    '401 | TOKEN_REUSE_DETECTED | Replay after the grace window; all sessions of the user are revoked.'
    and §10:
    'For grace-window expiry, at most one test may set REFRESH_GRACE_WINDOW_SECONDS=1 and wait a bounded 3 seconds.'
    """
    # Configure bounded 1-second grace window as explicitly allowed by spec §10
    monkeypatch.setattr(app_settings, "REFRESH_GRACE_WINDOW_SECONDS", 1)

    email = "reuse_victim@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Reuse Victim"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    r1 = login_res.json()["data"]["refresh_token"]

    # Rotate r1 -> r2
    rotate_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert rotate_res.status_code == 200
    r2 = rotate_res.json()["data"]["refresh_token"]

    # Wait 2 seconds (bounded <= 3s) for 1s grace window to expire
    await asyncio.sleep(2)

    # Replay r1 after grace window -> 401 TOKEN_REUSE_DETECTED
    replay_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert replay_res.status_code == 401
    assert "www-authenticate" not in replay_res.headers
    replay_body = replay_res.json()
    assert replay_body["success"] is False
    assert replay_body["data"] is None
    assert replay_body["error"]["code"] == "TOKEN_REUSE_DETECTED"

    # All sessions revoked: successor r2 must now yield 401 SESSION_REVOKED
    subsequent_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": r2})
    assert subsequent_res.status_code == 401
    assert "www-authenticate" not in subsequent_res.headers
    assert subsequent_res.json()["error"]["code"] == "SESSION_REVOKED"


@pytest.mark.asyncio
async def test_refresh_replay_within_grace_after_successor_revoked_yields_session_revoked(
    client: httpx.AsyncClient,
) -> None:
    """Spec: docs/specs/auth-b2.md §3:
    'Replaying a rotated token within the grace window after the successor was revoked (logout or revoke-all) yields 401 SESSION_REVOKED, not a new token.'
    """
    email = "grace_after_revoke@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Revoke User"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    r1 = login_res.json()["data"]["refresh_token"]

    # Rotate r1 -> r2
    rotate_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert rotate_res.status_code == 200
    r2 = rotate_res.json()["data"]["refresh_token"]

    # Logout successor r2
    logout_res = await client.post("/api/v1/auth/logout", json={"refresh_token": r2})
    assert logout_res.status_code == 200

    # Replay r1 within grace window
    replay_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert replay_res.status_code == 401
    assert "www-authenticate" not in replay_res.headers
    assert replay_res.json()["error"]["code"] == "SESSION_REVOKED"


@pytest.mark.asyncio
async def test_refresh_token_invalid_cases(
    client: httpx.AsyncClient,
    make_access_token: typing.Callable[..., str],
    make_refresh_token: typing.Callable[..., str],
) -> None:
    """Spec: docs/specs/auth-b2.md §6:
    '401 | TOKEN_INVALID | Tampered or unparseable token, wrong token type (for example an access token), or a non-UUID sub.'
    and:
    '401 responses carry no WWW-Authenticate header because the token travels in the body.'
    """
    # 1. Unparseable token
    res_bad = await client.post("/api/v1/auth/refresh", json={"refresh_token": "not.a.valid.jwt"})
    assert res_bad.status_code == 401
    assert "www-authenticate" not in res_bad.headers
    assert res_bad.json()["error"]["code"] == "TOKEN_INVALID"

    # 2. Tampered token (wrong secret key)
    tampered_token = make_refresh_token(key="wrong-secret-key-that-is-at-least-32-bytes-long")
    res_tampered = await client.post("/api/v1/auth/refresh", json={"refresh_token": tampered_token})
    assert res_tampered.status_code == 401
    assert "www-authenticate" not in res_tampered.headers
    assert res_tampered.json()["error"]["code"] == "TOKEN_INVALID"

    # 3. Wrong token type (access token passed instead of refresh token)
    access_tok = make_access_token()
    res_type = await client.post("/api/v1/auth/refresh", json={"refresh_token": access_tok})
    assert res_type.status_code == 401
    assert "www-authenticate" not in res_type.headers
    assert res_type.json()["error"]["code"] == "TOKEN_INVALID"

    # 4. Non-UUID sub claim
    non_uuid_tok = make_refresh_token(sub="not-a-uuid-string")
    res_sub = await client.post("/api/v1/auth/refresh", json={"refresh_token": non_uuid_tok})
    assert res_sub.status_code == 401
    assert "www-authenticate" not in res_sub.headers
    assert res_sub.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.asyncio
async def test_refresh_token_expired(
    client: httpx.AsyncClient,
    make_refresh_token: typing.Callable[..., str],
) -> None:
    """Spec: docs/specs/auth-b2.md §6:
    '401 | TOKEN_EXPIRED | Correctly signed refresh token past its exp.'
    """
    expired_token = make_refresh_token(exp_delta=-3600)
    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": expired_token})
    assert res.status_code == 401
    assert "www-authenticate" not in res.headers
    assert res.json()["error"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.asyncio
async def test_refresh_unknown_token_yields_session_revoked(
    client: httpx.AsyncClient,
    make_refresh_token: typing.Callable[..., str],
) -> None:
    """Spec: docs/specs/auth-b2.md §6:
    '401 | SESSION_REVOKED | Token unknown, logged out, or revoked.'
    """
    # 1. Register a valid user
    email = "existing_user_unknown_tok@example.com"
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": "Password123!", "full_name": "Valid User"},
    )
    user_id = reg_res.json()["data"]["id"]

    # 2. Forge a correctly-signed token for that user with an unrecorded/unknown jti
    unrecorded_token = make_refresh_token(sub=user_id, jti=str(uuid4()))
    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": unrecorded_token})
    assert res.status_code == 401
    assert "www-authenticate" not in res.headers
    assert res.json()["error"]["code"] == "SESSION_REVOKED"


@pytest.mark.asyncio
async def test_refresh_user_no_longer_exists_yields_unauthorized(
    client: httpx.AsyncClient,
    db_session: AsyncSession,
) -> None:
    """Spec: docs/specs/auth-b2.md §6:
    '401 | UNAUTHORIZED | The user no longer exists; the user\'s sessions are revoked.'
    """
    email = "deleted_refresh_user@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Deleted User"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    r1 = login_res.json()["data"]["refresh_token"]

    # Delete user from DB
    await db_session.execute(sa.text("DELETE FROM users WHERE email = :email"), {"email": email})
    await db_session.commit()

    res = await client.post("/api/v1/auth/refresh", json={"refresh_token": r1})
    assert res.status_code == 401
    assert "www-authenticate" not in res.headers
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"refresh_token": ""},
        {"refresh_token": "r" * 2049},  # > 2048 chars
    ],
)
@pytest.mark.asyncio
async def test_refresh_validation_errors(
    client: httpx.AsyncClient,
    payload: dict[str, str],
) -> None:
    """Spec: docs/specs/auth-b2.md §6:
    '422 | VALIDATION_ERROR | Missing or oversized token.'
    """
    res = await client.post("/api/v1/auth/refresh", json=payload)
    assert res.status_code == 422
    body = res.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["field"] == "refresh_token"


@pytest.mark.asyncio
async def test_refresh_per_ip_rate_limit(
    make_client: typing.Callable[[str], httpx.AsyncClient],
) -> None:
    """Spec: docs/specs/auth-b2.md §2:
    'Per-IP limit, refresh: 30 requests per 60 s'
    and §6:
    '429 | RATE_LIMIT_EXCEEDED | Per-IP limit; Retry-After present.'
    """
    ip1 = "192.0.2.130"
    ip2 = "192.0.2.131"

    async with make_client(ip1) as client1, make_client(ip2) as client2:
        for _ in range(30):
            res = await client1.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "dummy-token-rate-test"},
            )
            assert res.status_code == 401

        # 31st request from ip1 triggers per-IP rate limit
        blocked = await client1.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "dummy-token-rate-test"},
        )
        assert blocked.status_code == 429
        body = blocked.json()
        assert body["success"] is False
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "retry-after" in blocked.headers
        assert int(blocked.headers["retry-after"]) >= 1

        # Request from ip2 is not rate-limited
        other = await client2.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "dummy-token-rate-test"},
        )
        assert other.status_code == 401


@pytest.mark.asyncio
async def test_refresh_cors_on_error(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §9:
    'With an Origin listed in the CORS settings, error responses also carry Access-Control-Allow-Origin.'
    """
    res = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": "invalid.jwt.payload"},
        headers={"Origin": CORS_ORIGIN},
    )
    assert res.status_code == 401
    assert res.headers.get("access-control-allow-origin") == CORS_ORIGIN
