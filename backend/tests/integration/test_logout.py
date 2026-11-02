"""Integration tests for POST /api/v1/auth/logout.

Spec reference: docs/specs/auth-b2.md §7 and openapi.json.
"""

from __future__ import annotations

import typing

import httpx
import pytest

CORS_ORIGIN = "http://localhost:3000"


@pytest.mark.asyncio
async def test_logout_success_and_subsequent_refresh(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §7:
    '200 | none | data: {"status": "ok"}. The presented token\'s session is revoked.'
    and:
    'After logout, refreshing with that token returns 401 SESSION_REVOKED, and an already issued access token still works on /auth/me until it expires.'
    """
    email = "logout_success@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Logout User"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    tokens = login_res.json()["data"]
    access_tok = tokens["access_token"]
    refresh_tok = tokens["refresh_token"]

    # 1. Logout
    logout_res = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_tok})
    assert logout_res.status_code == 200
    logout_body = logout_res.json()
    assert logout_body["success"] is True
    assert logout_body["error"] is None
    assert logout_body["data"] == {"status": "ok"}

    # 2. Subsequent refresh with revoked token yields 401 SESSION_REVOKED
    refresh_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_tok})
    assert refresh_res.status_code == 401
    assert refresh_res.json()["error"]["code"] == "SESSION_REVOKED"

    # 3. Already issued access token still works on /auth/me until it expires
    me_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_tok}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["data"]["email"] == email


@pytest.mark.asyncio
async def test_logout_idempotency_same_token_twice(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §7:
    'Idempotent: logging out the same token twice returns 200 both times.'
    """
    email = "logout_idempotent@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Idempotent User"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    refresh_tok = login_res.json()["data"]["refresh_token"]

    # First logout
    res1 = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_tok})
    assert res1.status_code == 200
    assert res1.json()["data"] == {"status": "ok"}

    # Second logout with same token
    res2 = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_tok})
    assert res2.status_code == 200
    assert res2.json()["data"] == {"status": "ok"}


@pytest.mark.asyncio
async def test_logout_expired_token_returns_200(
    client: httpx.AsyncClient,
    make_refresh_token: typing.Callable[..., str],
) -> None:
    """Spec: docs/specs/auth-b2.md §7:
    'A correctly signed but expired refresh token also returns 200.'
    """
    expired_token = make_refresh_token(exp_delta=-3600)

    res = await client.post("/api/v1/auth/logout", json={"refresh_token": expired_token})
    assert res.status_code == 200
    assert res.json()["success"] is True
    assert res.json()["data"] == {"status": "ok"}


@pytest.mark.asyncio
async def test_logout_only_revokes_presented_session_other_sessions_work(
    client: httpx.AsyncClient,
) -> None:
    """Spec: docs/specs/auth-b2.md §7:
    'Only the presented jti is revoked. Other sessions of the same user keep working.'
    """
    email = "multi_session@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Multi User"},
    )

    # Session A
    login_a = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_a.status_code == 200
    refresh_a = login_a.json()["data"]["refresh_token"]

    # Session B
    login_b = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_b.status_code == 200
    refresh_b = login_b.json()["data"]["refresh_token"]
    assert refresh_a != refresh_b

    # Logout Session A only
    logout_res = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_a})
    assert logout_res.status_code == 200

    # Session A refresh is revoked
    ref_a_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_a})
    assert ref_a_res.status_code == 401
    assert ref_a_res.json()["error"]["code"] == "SESSION_REVOKED"

    # Session B refresh still works and rotates cleanly
    ref_b_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": refresh_b})
    assert ref_b_res.status_code == 200
    assert ref_b_res.json()["success"] is True


@pytest.mark.asyncio
async def test_logout_rotated_token_does_not_end_successor(
    client: httpx.AsyncClient,
) -> None:
    """Spec: docs/specs/auth-b2.md §7:
    'Presenting a token that has already been rotated away does not end its successor.'
    """
    email = "rotated_logout@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Rotated User"},
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

    # Logout with old r1
    logout_res = await client.post("/api/v1/auth/logout", json={"refresh_token": r1})
    assert logout_res.status_code == 200

    # Successor r2 must NOT be revoked and still works
    refresh_res = await client.post("/api/v1/auth/refresh", json={"refresh_token": r2})
    assert refresh_res.status_code == 200
    assert refresh_res.json()["success"] is True


@pytest.mark.asyncio
async def test_logout_token_invalid_cases(
    client: httpx.AsyncClient,
    make_access_token: typing.Callable[..., str],
    make_refresh_token: typing.Callable[..., str],
) -> None:
    """Spec: docs/specs/auth-b2.md §7:
    '401 | TOKEN_INVALID | Tampered or unparseable token, or wrong token type.'
    """
    # 1. Unparseable token
    res_bad = await client.post("/api/v1/auth/logout", json={"refresh_token": "not.a.valid.jwt"})
    assert res_bad.status_code == 401
    assert res_bad.json()["error"]["code"] == "TOKEN_INVALID"

    # 2. Tampered token (wrong secret key)
    tampered_token = make_refresh_token(key="wrong-secret-key-that-is-at-least-32-bytes-long")
    res_tampered = await client.post("/api/v1/auth/logout", json={"refresh_token": tampered_token})
    assert res_tampered.status_code == 401
    assert res_tampered.json()["error"]["code"] == "TOKEN_INVALID"

    # 3. Wrong token type (access token passed instead of refresh token)
    access_tok = make_access_token()
    res_type = await client.post("/api/v1/auth/logout", json={"refresh_token": access_tok})
    assert res_type.status_code == 401
    assert res_type.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"refresh_token": ""},
        {"refresh_token": "r" * 2049},  # > 2048 chars
    ],
)
@pytest.mark.asyncio
async def test_logout_validation_errors(
    client: httpx.AsyncClient,
    payload: dict[str, str],
) -> None:
    """Spec: docs/specs/auth-b2.md §7:
    '422 | VALIDATION_ERROR | Missing or oversized token.'
    """
    res = await client.post("/api/v1/auth/logout", json=payload)
    assert res.status_code == 422
    body = res.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["field"] == "refresh_token"


@pytest.mark.asyncio
async def test_logout_per_ip_rate_limit(
    make_client: typing.Callable[[str], httpx.AsyncClient],
) -> None:
    """Spec: docs/specs/auth-b2.md §2:
    'Per-IP limit, logout: 30 requests per 60 s'
    and §7:
    '429 | RATE_LIMIT_EXCEEDED | Per-IP limit; Retry-After present.'
    """
    ip1 = "192.0.2.140"
    ip2 = "192.0.2.141"

    async with make_client(ip1) as client1, make_client(ip2) as client2:
        for _ in range(30):
            res = await client1.post(
                "/api/v1/auth/logout",
                json={"refresh_token": "dummy-token-logout-test"},
            )
            assert res.status_code == 401

        # 31st request triggers rate limit
        blocked = await client1.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "dummy-token-logout-test"},
        )
        assert blocked.status_code == 429
        body = blocked.json()
        assert body["success"] is False
        assert body["data"] is None
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "retry-after" in blocked.headers
        assert int(blocked.headers["retry-after"]) >= 1

        # Request from ip2 is not rate-limited
        other = await client2.post(
            "/api/v1/auth/logout",
            json={"refresh_token": "dummy-token-logout-test"},
        )
        assert other.status_code == 401


@pytest.mark.asyncio
async def test_logout_cors_on_error(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §9:
    'With an Origin listed in the CORS settings, error responses also carry Access-Control-Allow-Origin.'
    """
    res = await client.post(
        "/api/v1/auth/logout",
        json={"refresh_token": "invalid.jwt.token"},
        headers={"Origin": CORS_ORIGIN},
    )
    assert res.status_code == 401
    assert res.headers.get("access-control-allow-origin") == CORS_ORIGIN
