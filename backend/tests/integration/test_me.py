"""Integration tests for GET /api/v1/auth/me.

Spec reference: docs/specs/auth-b2.md §8 and openapi.json.
"""

from __future__ import annotations

import typing
from uuid import UUID, uuid4

import httpx
import pytest

CORS_ORIGIN = "http://localhost:3000"


@pytest.mark.asyncio
async def test_me_success(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §8:
    '200 | none | data: the same user object as registration.'
    """
    email = "me_user@example.com"
    password = "ValidPassword123!"
    full_name = "Jane Me User"

    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": full_name},
    )
    assert reg_res.status_code == 201

    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_res.status_code == 200
    access_token = login_res.json()["data"]["access_token"]

    me_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_token}"},
    )
    assert me_res.status_code == 200
    body = me_res.json()
    assert body["success"] is True
    assert body["error"] is None

    data = body["data"]
    assert UUID(data["id"])
    assert data["email"] == email
    assert data["full_name"] == full_name
    assert data["is_verified"] is False
    assert data["oauth_provider"] is None
    assert "created_at" in data
    assert "password" not in data
    assert "hashed_password" not in data


@pytest.mark.parametrize(
    "auth_header",
    [
        None,  # Missing header
        "",  # Empty header
        "Basic dXNlcjpwYXNz",  # Non-bearer scheme
        "Bearer",  # Empty bearer value
        "Token some-random-token",  # Other scheme
    ],
)
@pytest.mark.asyncio
async def test_me_unauthorized_header_formats(
    client: httpx.AsyncClient,
    auth_header: str | None,
) -> None:
    """Spec: docs/specs/auth-b2.md §8:
    '401 | UNAUTHORIZED | Header missing, empty, or not a Bearer scheme; or the user no longer exists.'
    and:
    'Every 401 from this endpoint carries a WWW-Authenticate header that starts with Bearer.'
    """
    headers = {}
    if auth_header is not None:
        headers["Authorization"] = auth_header

    res = await client.get("/api/v1/auth/me", headers=headers)
    assert res.status_code == 401
    assert "www-authenticate" in res.headers
    assert res.headers["www-authenticate"].startswith("Bearer")

    body = res.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_me_token_invalid_cases(
    client: httpx.AsyncClient,
    make_access_token: typing.Callable[..., str],
    make_refresh_token: typing.Callable[..., str],
) -> None:
    """Spec: docs/specs/auth-b2.md §8:
    '401 | TOKEN_INVALID | Tampered token, or a refresh token used as an access token.'
    and:
    'Every 401 from this endpoint carries a WWW-Authenticate header that starts with Bearer.'
    """
    # 1. Unparseable token
    res_bad = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": "Bearer not.a.valid.jwt"},
    )
    assert res_bad.status_code == 401
    assert res_bad.headers.get("www-authenticate", "").startswith("Bearer")
    assert res_bad.json()["error"]["code"] == "TOKEN_INVALID"

    # 2. Tampered signature
    tampered_tok = make_access_token(key="wrong-key-secret-that-is-at-least-32-bytes")
    res_tampered = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {tampered_tok}"},
    )
    assert res_tampered.status_code == 401
    assert res_tampered.headers.get("www-authenticate", "").startswith("Bearer")
    assert res_tampered.json()["error"]["code"] == "TOKEN_INVALID"

    # 3. Refresh token used as access token
    refresh_tok = make_refresh_token()
    res_type = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {refresh_tok}"},
    )
    assert res_type.status_code == 401
    assert res_type.headers.get("www-authenticate", "").startswith("Bearer")
    assert res_type.json()["error"]["code"] == "TOKEN_INVALID"

    # 4. Non-UUID sub claim
    non_uuid_tok = make_access_token(sub="not-a-uuid-string")
    res_sub = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {non_uuid_tok}"},
    )
    assert res_sub.status_code == 401
    assert res_sub.headers.get("www-authenticate", "").startswith("Bearer")
    assert res_sub.json()["error"]["code"] == "TOKEN_INVALID"


@pytest.mark.asyncio
async def test_me_token_expired(
    client: httpx.AsyncClient,
    make_access_token: typing.Callable[..., str],
) -> None:
    """Spec: docs/specs/auth-b2.md §8:
    '401 | TOKEN_EXPIRED | Correctly signed access token past its exp.'
    and:
    'Every 401 from this endpoint carries a WWW-Authenticate header that starts with Bearer.'
    """
    expired_tok = make_access_token(exp_delta=-3600)

    res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_tok}"},
    )
    assert res.status_code == 401
    assert "www-authenticate" in res.headers
    assert res.headers["www-authenticate"].startswith("Bearer")
    assert res.json()["error"]["code"] == "TOKEN_EXPIRED"


@pytest.mark.asyncio
async def test_me_user_no_longer_exists(
    client: httpx.AsyncClient,
    make_access_token: typing.Callable[..., str],
) -> None:
    """Spec: docs/specs/auth-b2.md §8:
    '401 | UNAUTHORIZED | Header missing, empty, or not a Bearer scheme; or the user no longer exists.'
    and:
    'Every 401 from this endpoint carries a WWW-Authenticate header that starts with Bearer.'
    """
    ghost_user_id = str(uuid4())
    ghost_tok = make_access_token(sub=ghost_user_id)

    res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {ghost_tok}"},
    )
    assert res.status_code == 401
    assert "www-authenticate" in res.headers
    assert res.headers["www-authenticate"].startswith("Bearer")
    assert res.json()["error"]["code"] == "UNAUTHORIZED"


@pytest.mark.asyncio
async def test_me_stateless_access_token_survives_logout(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §3:
    'Access tokens are stateless. Logout and revocation do not invalidate an access token before its exp.'
    """
    email = "stateless_token@example.com"
    password = "ValidPassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Stateless User"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    tokens = login_res.json()["data"]
    access_tok = tokens["access_token"]
    refresh_tok = tokens["refresh_token"]

    # Logout
    logout_res = await client.post("/api/v1/auth/logout", json={"refresh_token": refresh_tok})
    assert logout_res.status_code == 200

    # Access token must continue to function on /auth/me
    me_res = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {access_tok}"},
    )
    assert me_res.status_code == 200
    assert me_res.json()["data"]["email"] == email


@pytest.mark.asyncio
async def test_me_cors_headers_on_success_and_error(
    client: httpx.AsyncClient,
    make_access_token: typing.Callable[..., str],
) -> None:
    """Spec: docs/specs/auth-b2.md §9:
    'With an Origin listed in the CORS settings, error responses also carry Access-Control-Allow-Origin.'
    """
    # 1. Error response (401)
    res_err = await client.get(
        "/api/v1/auth/me",
        headers={"Origin": CORS_ORIGIN},
    )
    assert res_err.status_code == 401
    assert res_err.headers.get("access-control-allow-origin") == CORS_ORIGIN

    # 2. Success response (200)
    email = "me_cors@example.com"
    password = "ValidPassword123!"
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "CORS User"},
    )
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    access_tok = login_res.json()["data"]["access_token"]

    res_ok = await client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {access_tok}",
            "Origin": CORS_ORIGIN,
        },
    )
    assert res_ok.status_code == 200
    assert res_ok.headers.get("access-control-allow-origin") == CORS_ORIGIN
