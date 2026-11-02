"""Integration tests for POST /api/v1/auth/register.

Spec reference: docs/specs/auth-b2.md §4 and openapi.json.
"""

from __future__ import annotations

import asyncio
import typing
from uuid import UUID

import httpx
import pytest

CORS_ORIGIN = "http://localhost:3000"


@pytest.mark.asyncio
async def test_register_success(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §4:
    '201 | none | Created. data: id, email, full_name (trimmed), is_verified = false, oauth_provider = null, created_at. No password or hash anywhere.'
    'Surrounding whitespace is ignored.'
    'No tokens are issued.'
    """
    payload = {
        "email": "  NewUser_01@Example.com  ",
        "password": "Password123!",
        "full_name": "   Jane Doe Registration   ",
    }
    res = await client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 201

    body = res.json()
    assert body["success"] is True
    assert body["error"] is None

    data = body["data"]
    assert isinstance(data, dict)
    assert UUID(data["id"])  # Valid UUID
    assert data["email"] == "newuser_01@example.com"
    assert data["full_name"] == "Jane Doe Registration"
    assert data["is_verified"] is False
    assert data["oauth_provider"] is None
    assert "created_at" in data

    # Verify no tokens or sensitive information in response
    assert "password" not in data
    assert "hashed_password" not in data
    assert "access_token" not in data
    assert "refresh_token" not in data


@pytest.mark.asyncio
async def test_register_email_case_insensitivity_and_normalization(
    client: httpx.AsyncClient,
) -> None:
    """Spec: docs/specs/auth-b2.md §4:
    'Email comparison is case-insensitive. A@x.com and a@x.com are the same account. The returned email is lowercase. Surrounding whitespace is ignored.'
    """
    payload = {
        "email": "CaseNormalize_User@Domain.ORG",
        "password": "ValidPassword999!",
        "full_name": "Case Test",
    }
    res = await client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 201
    assert res.json()["data"]["email"] == "casenormalize_user@domain.org"


@pytest.mark.asyncio
async def test_register_duplicate_email_conflict_including_case_variants(
    client: httpx.AsyncClient,
) -> None:
    """Spec: docs/specs/auth-b2.md §4:
    '409 | EMAIL_TAKEN (field = email) | Email already registered, including case variants.'
    """
    initial_payload = {
        "email": "duplicate_check@example.com",
        "password": "ValidPassword123!",
        "full_name": "Primary User",
    }
    res1 = await client.post("/api/v1/auth/register", json=initial_payload)
    assert res1.status_code == 201

    # Exact duplicate registration
    res2 = await client.post("/api/v1/auth/register", json=initial_payload)
    assert res2.status_code == 409
    body2 = res2.json()
    assert body2["success"] is False
    assert body2["data"] is None
    assert body2["error"]["code"] == "EMAIL_TAKEN"
    assert body2["error"]["field"] == "email"

    # Uppercase variant registration
    variant_payload = {
        "email": "DUPLICATE_CHECK@EXAMPLE.COM",
        "password": "AnotherPassword456!",
        "full_name": "Variant User",
    }
    res3 = await client.post("/api/v1/auth/register", json=variant_payload)
    assert res3.status_code == 409
    body3 = res3.json()
    assert body3["success"] is False
    assert body3["data"] is None
    assert body3["error"]["code"] == "EMAIL_TAKEN"
    assert body3["error"]["field"] == "email"


@pytest.mark.asyncio
async def test_register_concurrency_exactly_one_success(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §4:
    'Concurrent registration of one email: exactly one 201, all others 409.'
    """
    email = "concurrent_reg@example.com"
    tasks = [
        client.post(
            "/api/v1/auth/register",
            json={
                "email": email,
                "password": f"Password{i}123!",
                "full_name": f"Concurrent Candidate {i}",
            },
        )
        for i in range(5)
    ]
    responses = await asyncio.gather(*tasks)

    status_codes = [r.status_code for r in responses]
    assert status_codes.count(201) == 1
    assert status_codes.count(409) == 4

    for r in responses:
        if r.status_code == 409:
            body = r.json()
            assert body["success"] is False
            assert body["data"] is None
            assert body["error"]["code"] == "EMAIL_TAKEN"
            assert body["error"]["field"] == "email"


@pytest.mark.parametrize(
    ("payload", "expected_field"),
    [
        (
            {"email": "not-an-email", "password": "Password123!", "full_name": "Valid Name"},
            "email",
        ),
        (
            {
                "email": "a" * 243 + "@example.com",
                "password": "Password123!",
                "full_name": "Name",
            },  # > 254 chars
            "email",
        ),
        (
            {
                "email": "valid@example.com",
                "password": "short",
                "full_name": "Valid Name",
            },  # < 8 chars
            "password",
        ),
        (
            {
                "email": "valid@example.com",
                "password": "p" * 129,
                "full_name": "Valid Name",
            },  # > 128 chars
            "password",
        ),
        (
            {
                "email": "valid@example.com",
                "password": "Password123!",
                "full_name": "   ",
            },  # whitespace-only
            "full_name",
        ),
        (
            {
                "email": "valid@example.com",
                "password": "Password123!",
                "full_name": "",
            },  # empty string
            "full_name",
        ),
        (
            {
                "email": "valid@example.com",
                "password": "Password123!",
                "full_name": "n" * 201,
            },  # > 200 chars
            "full_name",
        ),
    ],
)
@pytest.mark.asyncio
async def test_register_validation_errors(
    client: httpx.AsyncClient,
    payload: dict[str, str],
    expected_field: str,
) -> None:
    """Spec: docs/specs/auth-b2.md §4:
    '422 | VALIDATION_ERROR | Any bound or format violation.'
    and §1:
    'Validation failures: 422, VALIDATION_ERROR, field names the first failing field.'
    """
    res = await client.post("/api/v1/auth/register", json=payload)
    assert res.status_code == 422
    body = res.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["field"] == expected_field
    assert isinstance(body["error"]["message"], str)


@pytest.mark.asyncio
async def test_register_per_ip_rate_limit(
    make_client: typing.Callable[[str], httpx.AsyncClient],
) -> None:
    """Spec: docs/specs/auth-b2.md §2:
    'Per-IP limit, register: 5 requests per 60 s'
    and §4:
    '429 | RATE_LIMIT_EXCEEDED | Per-IP limit; Retry-After present.'
    """
    ip1 = "192.0.2.110"
    ip2 = "192.0.2.111"

    async with make_client(ip1) as client1, make_client(ip2) as client2:
        # 5 allowed requests within the 60s window from ip1
        for i in range(5):
            res = await client1.post(
                "/api/v1/auth/register",
                json={
                    "email": f"rate_user_{i}@example.com",
                    "password": "Password123!",
                    "full_name": f"Rate User {i}",
                },
            )
            assert res.status_code == 201

        # 6th request from the same IP must be rejected with 429
        blocked_res = await client1.post(
            "/api/v1/auth/register",
            json={
                "email": "rate_user_blocked@example.com",
                "password": "Password123!",
                "full_name": "Blocked User",
            },
        )
        assert blocked_res.status_code == 429
        body = blocked_res.json()
        assert body["success"] is False
        assert body["data"] is None
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "retry-after" in blocked_res.headers
        retry_after = int(blocked_res.headers["retry-after"])
        assert retry_after >= 1

        # An independent IP address must not be blocked
        other_res = await client2.post(
            "/api/v1/auth/register",
            json={
                "email": "rate_user_allowed@example.com",
                "password": "Password123!",
                "full_name": "Allowed User",
            },
        )
        assert other_res.status_code == 201


@pytest.mark.asyncio
async def test_register_cors_on_error(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §9:
    'With an Origin listed in the CORS settings, error responses also carry Access-Control-Allow-Origin.'
    """
    res = await client.post(
        "/api/v1/auth/register",
        json={"email": "not-valid", "password": "short", "full_name": ""},
        headers={"Origin": CORS_ORIGIN},
    )
    assert res.status_code == 422
    assert res.headers.get("access-control-allow-origin") == CORS_ORIGIN
