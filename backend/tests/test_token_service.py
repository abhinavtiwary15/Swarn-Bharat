"""Tests for refresh token storage, atomic rotation, and user session management."""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest

from backend.core.redis import redis_tokens
from backend.services.token_service import (
    TokenNotFoundError,
    TokenReuseError,
    is_token_active,
    record_issued_token,
    revoke_all_for_user,
    revoke_token,
    rotate_token,
)


@pytest.fixture(autouse=True)
async def cleanup_token_redis() -> AsyncIterator[None]:
    """Isolate token Redis state across test cases."""
    await redis_tokens.flushdb()
    yield
    await redis_tokens.flushdb()


@pytest.mark.asyncio
async def test_token_service_issuance_and_active_check() -> None:
    user_id = uuid4()
    jti = str(uuid4())
    assert await is_token_active(jti) is False
    await record_issued_token(user_id, jti)
    assert await is_token_active(jti) is True


@pytest.mark.asyncio
async def test_token_service_rotation_normal() -> None:
    user_id = uuid4()
    old_jti = str(uuid4())
    new_jti = str(uuid4())
    await record_issued_token(user_id, old_jti)

    res = await rotate_token(user_id, old_jti, new_jti)
    assert res.status == "ok"
    assert res.jti == new_jti
    assert await is_token_active(new_jti) is True
    assert await is_token_active(old_jti) is False


@pytest.mark.asyncio
async def test_token_service_grace_window() -> None:
    user_id = uuid4()
    old_jti = str(uuid4())
    first_new_jti = str(uuid4())
    second_new_jti = str(uuid4())
    await record_issued_token(user_id, old_jti)

    res1 = await rotate_token(user_id, old_jti, first_new_jti, grace_window_seconds=10)
    assert res1.status == "ok"
    assert res1.jti == first_new_jti

    # Second concurrent or repeated rotation inside grace window returns first replacement jti
    res2 = await rotate_token(user_id, old_jti, second_new_jti, grace_window_seconds=10)
    assert res2.status == "grace"
    assert res2.jti == first_new_jti


@pytest.mark.asyncio
async def test_token_service_concurrent_rotation() -> None:
    user_id = uuid4()
    old_jti = str(uuid4())
    await record_issued_token(user_id, old_jti)

    candidates = [str(uuid4()) for _ in range(5)]
    tasks = [rotate_token(user_id, old_jti, cand, grace_window_seconds=30) for cand in candidates]
    results = await asyncio.gather(*tasks)

    ok_results = [r for r in results if r.status == "ok"]
    grace_results = [r for r in results if r.status == "grace"]

    # Exactly one candidate succeeds as "ok", others receive "grace"
    assert len(ok_results) == 1
    winner_jti = ok_results[0].jti
    assert len(grace_results) == 4
    for gr in grace_results:
        assert gr.jti == winner_jti


@pytest.mark.asyncio
async def test_token_service_logout_vs_reuse() -> None:
    user_id = uuid4()
    jti_a = str(uuid4())
    jti_b = str(uuid4())

    await record_issued_token(user_id, jti_a)
    await record_issued_token(user_id, jti_b)

    # 1. Single token logout (revocation)
    await revoke_token(user_id, jti_a)
    assert await is_token_active(jti_a) is False
    assert await is_token_active(jti_b) is True

    # Attempting to rotate logged-out token raises TokenNotFoundError (NOT TokenReuseError)
    with pytest.raises(TokenNotFoundError):
        await rotate_token(user_id, jti_a, str(uuid4()))

    # Token B remains active after Token A's logout
    assert await is_token_active(jti_b) is True

    # 2. Token reuse outside grace window
    old_jti = str(uuid4())
    new_jti = str(uuid4())
    await record_issued_token(user_id, old_jti)
    await rotate_token(user_id, old_jti, new_jti, grace_window_seconds=0)

    # Replay of old_jti outside grace window triggers TokenReuseError and revokes all user tokens
    with pytest.raises(TokenReuseError):
        await rotate_token(user_id, old_jti, str(uuid4()), grace_window_seconds=0)

    assert await is_token_active(new_jti) is False
    assert await is_token_active(jti_b) is False


@pytest.mark.asyncio
async def test_token_service_reuse_revokes_other_sessions() -> None:
    user_id = uuid4()
    session_1 = str(uuid4())
    session_2 = str(uuid4())
    session_3 = str(uuid4())

    await record_issued_token(user_id, session_1)
    await record_issued_token(user_id, session_2)

    # Rotate session_1 -> session_3
    await rotate_token(user_id, session_1, session_3, grace_window_seconds=0)
    assert await is_token_active(session_3) is True
    assert await is_token_active(session_2) is True

    # Replaying session_1 triggers TokenReuseError and revokes all user sessions
    with pytest.raises(TokenReuseError):
        await rotate_token(user_id, session_1, str(uuid4()), grace_window_seconds=0)

    # Both session_2 and replacement session_3 are now revoked
    assert await is_token_active(session_1) is False
    assert await is_token_active(session_2) is False
    assert await is_token_active(session_3) is False


@pytest.mark.asyncio
async def test_token_service_user_id_argument_required() -> None:
    jti = str(uuid4())
    # Calling without user_id raises TypeError (positional argument required)
    with pytest.raises(TypeError):
        await record_issued_token(jti)  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        await rotate_token(jti, str(uuid4()))  # type: ignore[call-arg]

    with pytest.raises(TypeError):
        await revoke_token(jti)  # type: ignore[call-arg]

    # Calling with UUID and str user_id succeeds
    user_uuid = uuid4()
    user_str = str(uuid4())
    jti_1 = str(uuid4())
    jti_2 = str(uuid4())

    await record_issued_token(user_uuid, jti_1)
    await record_issued_token(user_str, jti_2)

    assert await is_token_active(jti_1) is True
    assert await is_token_active(jti_2) is True

    await revoke_token(user_uuid, jti_1)
    await revoke_token(user_str, jti_2)

    assert await is_token_active(jti_1) is False
    assert await is_token_active(jti_2) is False


@pytest.mark.asyncio
async def test_token_service_rotation_races_revoke_all_no_session_survives() -> None:
    user_id = uuid4()
    old_jti = str(uuid4())
    new_jti = str(uuid4())
    await record_issued_token(user_id, old_jti)

    async def _rotate() -> None:
        with contextlib.suppress(TokenNotFoundError, TokenReuseError):
            await rotate_token(user_id, old_jti, new_jti)

    async def _revoke() -> None:
        await revoke_all_for_user(user_id)

    # Launch rotation and revoke-all concurrently
    await asyncio.gather(_rotate(), _revoke())

    # After race settles, no session survives
    assert await is_token_active(old_jti) is False
    assert await is_token_active(new_jti) is False
