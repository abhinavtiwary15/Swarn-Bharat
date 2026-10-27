"""Tests for Redis fixed-window rate limiter."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_rate_limit_allows_within_limit(client: AsyncClient) -> None:
    for _ in range(2):
        r = await client.get("/_test/rate-limited")
        assert r.status_code == 200
        assert r.json()["ok"] is True


@pytest.mark.asyncio
async def test_rate_limit_blocks_third_request(client: AsyncClient) -> None:
    for _ in range(2):
        await client.get("/_test/rate-limited")

    r = await client.get("/_test/rate-limited")
    assert r.status_code == 429

    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "RATE_LIMIT_EXCEEDED"
    assert body["data"] is None


@pytest.mark.asyncio
async def test_rate_limit_retry_after_header(client: AsyncClient) -> None:
    for _ in range(2):
        await client.get("/_test/rate-limited")

    r = await client.get("/_test/rate-limited")
    assert r.status_code == 429
    assert "retry-after" in r.headers
    assert int(r.headers["retry-after"]) > 0


@pytest.mark.asyncio
async def test_rate_limit_resets_after_flush(client: AsyncClient) -> None:
    r = await client.get("/_test/rate-limited")
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_rate_limit_different_path_independent(client: AsyncClient) -> None:
    for _ in range(2):
        await client.get("/_test/rate-limited")
    blocked = await client.get("/_test/rate-limited")
    assert blocked.status_code == 429

    r = await client.get("/_test/other")
    assert r.status_code == 200
    assert r.json() == {"ok": True}


@pytest.mark.asyncio
async def test_rate_limit_redis_down_returns_503(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import redis.exceptions

    from backend.core.redis import redis_rl

    def _failing_pipeline(*args: object, **kwargs: object) -> None:
        raise redis.exceptions.ConnectionError("Redis connection lost")

    monkeypatch.setattr(redis_rl, "pipeline", _failing_pipeline)
    r = await client.get("/_test/rate-limited")
    assert r.status_code == 503
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "RATE_LIMITER_UNAVAILABLE"
    assert "retry-after" in r.headers
