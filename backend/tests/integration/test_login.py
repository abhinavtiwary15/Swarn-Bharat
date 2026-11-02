"""Integration tests for POST /api/v1/auth/login.

Spec reference: docs/specs/auth-b2.md §5 and openapi.json.
"""

from __future__ import annotations

import typing

import httpx
import pytest

CORS_ORIGIN = "http://localhost:3000"


@pytest.mark.asyncio
async def test_login_success_and_headers(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §5:
    '200 | none | data: access_token, refresh_token, token_type = bearer, expires_in = 900. Headers Cache-Control: no-store, Pragma: no-cache. The failure counter for the email is cleared.'
    """
    email = "login_success@example.com"
    password = "CorrectPassword123!"

    # 1. Register account
    reg_res = await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Login User"},
    )
    assert reg_res.status_code == 201

    # 2. Login
    login_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert login_res.status_code == 200

    # 3. Headers
    assert login_res.headers.get("cache-control") == "no-store"
    assert login_res.headers.get("pragma") == "no-cache"

    # 4. Body envelope & payload
    body = login_res.json()
    assert body["success"] is True
    assert body["error"] is None
    data = body["data"]
    assert isinstance(data["access_token"], str) and len(data["access_token"]) > 0
    assert isinstance(data["refresh_token"], str) and len(data["refresh_token"]) > 0
    assert data["token_type"] == "bearer"
    assert data["expires_in"] == 900


@pytest.mark.asyncio
async def test_login_case_insensitivity(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §5:
    'Email is case-insensitive.'
    """
    reg_email = "CaseTestUser@Example.Com"
    password = "Password123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": reg_email, "password": password, "full_name": "Case User"},
    )

    # Login with lower case
    res_lower = await client.post(
        "/api/v1/auth/login",
        json={"email": "casetestuser@example.com", "password": password},
    )
    assert res_lower.status_code == 200
    assert res_lower.json()["success"] is True

    # Login with upper case
    res_upper = await client.post(
        "/api/v1/auth/login",
        json={"email": "CASETESTUSER@EXAMPLE.COM", "password": password},
    )
    assert res_upper.status_code == 200
    assert res_upper.json()["success"] is True


@pytest.mark.asyncio
async def test_login_invalid_credentials_identical_body_anti_enumeration(
    client: httpx.AsyncClient,
) -> None:
    """Spec: docs/specs/auth-b2.md §5:
    '401 | INVALID_CREDENTIALS | Wrong password or unknown email. The two cases return identical status and body.'
    and §1:
    'Messages are not part of the contract, except that two responses documented as identical must have identical bodies.'
    """
    registered_email = "known_identity@example.com"
    correct_password = "ActualPassword123!"
    wrong_password = "WrongPassword999!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": registered_email, "password": correct_password, "full_name": "Known User"},
    )

    # 1. Known email with wrong password
    res_wrong_pw = await client.post(
        "/api/v1/auth/login",
        json={"email": registered_email, "password": wrong_password},
    )
    assert res_wrong_pw.status_code == 401
    body_wrong_pw = res_wrong_pw.json()
    assert body_wrong_pw["success"] is False
    assert body_wrong_pw["data"] is None
    assert body_wrong_pw["error"]["code"] == "INVALID_CREDENTIALS"

    # 2. Unknown email
    res_unknown_email = await client.post(
        "/api/v1/auth/login",
        json={"email": "completely_unknown_user@example.com", "password": wrong_password},
    )
    assert res_unknown_email.status_code == 401
    body_unknown_email = res_unknown_email.json()

    # Bodies must be character-for-character / schema identical
    assert body_wrong_pw == body_unknown_email


@pytest.mark.parametrize(
    ("payload", "expected_field"),
    [
        ({"email": "not-an-email", "password": "Password123!"}, "email"),
        ({"email": "a" * 243 + "@example.com", "password": "Password123!"}, "email"),  # > 254 chars
        ({"email": "user@example.com", "password": ""}, "password"),  # minLength: 1
        ({"email": "user@example.com", "password": "p" * 129}, "password"),  # > 128 chars
    ],
)
@pytest.mark.asyncio
async def test_login_validation_errors(
    client: httpx.AsyncClient,
    payload: dict[str, str],
    expected_field: str,
) -> None:
    """Spec: docs/specs/auth-b2.md §5:
    '422 | VALIDATION_ERROR | Bound or format violation.'
    and §1:
    'Validation failures: 422, VALIDATION_ERROR, field names the first failing field.'
    """
    res = await client.post("/api/v1/auth/login", json=payload)
    assert res.status_code == 422
    body = res.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "VALIDATION_ERROR"
    assert body["error"]["field"] == expected_field
    assert isinstance(body["error"]["message"], str)


@pytest.mark.asyncio
async def test_login_per_ip_rate_limit(
    make_client: typing.Callable[[str], httpx.AsyncClient],
) -> None:
    """Spec: docs/specs/auth-b2.md §2:
    'Per-IP limit, login: 5 requests per 60 s'
    and §5:
    '429 | RATE_LIMIT_EXCEEDED | Per-IP limit; Retry-After present.'
    """
    ip1 = "192.0.2.120"
    ip2 = "192.0.2.121"

    async with make_client(ip1) as client1, make_client(ip2) as client2:
        for i in range(5):
            res = await client1.post(
                "/api/v1/auth/login",
                json={"email": f"ip_user_{i}@example.com", "password": "SomePassword123!"},
            )
            assert res.status_code == 401

        # 6th request from ip1 triggers per-IP rate limit
        blocked = await client1.post(
            "/api/v1/auth/login",
            json={"email": "ip_user_blocked@example.com", "password": "SomePassword123!"},
        )
        assert blocked.status_code == 429
        body = blocked.json()
        assert body["success"] is False
        assert body["data"] is None
        assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
        assert "retry-after" in blocked.headers
        assert int(blocked.headers["retry-after"]) >= 1

        # Different IP is not blocked
        other = await client2.post(
            "/api/v1/auth/login",
            json={"email": "ip_user_other@example.com", "password": "SomePassword123!"},
        )
        assert other.status_code == 401


@pytest.mark.asyncio
async def test_login_account_lockout_known_email(
    client: httpx.AsyncClient,
    redis_rl_client: typing.Any,
) -> None:
    """Spec: docs/specs/auth-b2.md §5:
    'Lockout rules:
    - Every login attempt for a normalized email counts toward a fixed window that starts with the first attempt and lasts 900 seconds. The window is not extended by later attempts.
    - Attempts 1 to 10 in a window are evaluated normally. A wrong password returns 401.
    - Attempt 11 and later in the same window return 429 ACCOUNT_LOCKED before any password check, even when the password is correct. Retry-After equals the remaining time of the window.
    - Tests may flush the rate-limit Redis database between requests to exercise the lockout.'
    """
    target_email = "lockout_target@example.com"
    correct_password = "TargetPassword123!"

    # 1. Register target user
    await client.post(
        "/api/v1/auth/register",
        json={"email": target_email, "password": correct_password, "full_name": "Target User"},
    )

    # 2. Make 10 failed login attempts, flushing rate limit redis between each to avoid per-IP limit
    for attempt in range(1, 11):
        await redis_rl_client.flushdb()
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": target_email, "password": f"WrongAttempt{attempt}!"},
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

    # 3. Attempt 11 must return 429 ACCOUNT_LOCKED even before password check
    await redis_rl_client.flushdb()
    locked_res = await client.post(
        "/api/v1/auth/login",
        json={"email": target_email, "password": "AnyPassword!"},
    )
    assert locked_res.status_code == 429
    locked_body = locked_res.json()
    assert locked_body["success"] is False
    assert locked_body["data"] is None
    assert locked_body["error"]["code"] == "ACCOUNT_LOCKED"
    assert "retry-after" in locked_res.headers
    retry_after = int(locked_res.headers["retry-after"])
    assert 1 <= retry_after <= 900

    # 4. Attempt 12 even with CORRECT password must still return 429 ACCOUNT_LOCKED
    await redis_rl_client.flushdb()
    correct_locked_res = await client.post(
        "/api/v1/auth/login",
        json={"email": target_email, "password": correct_password},
    )
    assert correct_locked_res.status_code == 429
    assert correct_locked_res.json()["error"]["code"] == "ACCOUNT_LOCKED"


@pytest.mark.asyncio
async def test_login_account_lockout_unknown_email_identical(
    client: httpx.AsyncClient,
    redis_rl_client: typing.Any,
) -> None:
    """Spec: docs/specs/auth-b2.md §5:
    'Unknown emails are counted and locked exactly like known ones. A locked response must not reveal whether the account exists.'
    """
    unknown_target = "ghost_unknown_user@example.com"

    for _ in range(10):
        await redis_rl_client.flushdb()
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": unknown_target, "password": "WrongPassword123!"},
        )
        assert res.status_code == 401
        assert res.json()["error"]["code"] == "INVALID_CREDENTIALS"

    # Attempt 11 must return 429 ACCOUNT_LOCKED
    await redis_rl_client.flushdb()
    locked_res = await client.post(
        "/api/v1/auth/login",
        json={"email": unknown_target, "password": "WrongPassword123!"},
    )
    assert locked_res.status_code == 429
    body = locked_res.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "ACCOUNT_LOCKED"
    assert "retry-after" in locked_res.headers
    assert 1 <= int(locked_res.headers["retry-after"]) <= 900


@pytest.mark.asyncio
async def test_login_successful_login_clears_counter(
    client: httpx.AsyncClient,
    redis_rl_client: typing.Any,
) -> None:
    """Spec: docs/specs/auth-b2.md §5:
    'A successful login clears the counter.'
    """
    email = "reset_counter@example.com"
    password = "SafePassword123!"

    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "full_name": "Reset Counter User"},
    )

    # 3 failed attempts
    for _ in range(3):
        await redis_rl_client.flushdb()
        res = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword123!"},
        )
        assert res.status_code == 401

    # 1 successful login -> clears counter
    await redis_rl_client.flushdb()
    ok_res = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": password},
    )
    assert ok_res.status_code == 200

    # Next 10 failed attempts should all succeed in returning 401 (not 429 at attempt 8)
    for _ in range(10):
        await redis_rl_client.flushdb()
        fail_res = await client.post(
            "/api/v1/auth/login",
            json={"email": email, "password": "WrongPassword123!"},
        )
        assert fail_res.status_code == 401
        assert fail_res.json()["error"]["code"] == "INVALID_CREDENTIALS"

    # Attempt 11 returns 429
    await redis_rl_client.flushdb()
    locked = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "WrongPassword123!"},
    )
    assert locked.status_code == 429
    assert locked.json()["error"]["code"] == "ACCOUNT_LOCKED"


@pytest.mark.asyncio
async def test_login_cors_on_error(client: httpx.AsyncClient) -> None:
    """Spec: docs/specs/auth-b2.md §9:
    'With an Origin listed in the CORS settings, error responses also carry Access-Control-Allow-Origin.'
    """
    res = await client.post(
        "/api/v1/auth/login",
        json={"email": "nobody@example.com", "password": "WrongPassword123!"},
        headers={"Origin": CORS_ORIGIN},
    )
    assert res.status_code == 401
    assert res.headers.get("access-control-allow-origin") == CORS_ORIGIN
