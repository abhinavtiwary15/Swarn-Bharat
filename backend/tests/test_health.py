"""Tests for health check endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_live_returns_200(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health/live")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["error"] is None
    data = body["data"]
    assert data["status"] == "ok"
    assert "version" in data
    assert data["db_ok"] is True
    assert data["redis_ok"] is True


@pytest.mark.asyncio
async def test_health_ready_returns_200(client: AsyncClient) -> None:
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    assert body["error"] is None
    data = body["data"]
    assert data["status"] == "ok"
    assert data["db_ok"] is True
    assert data["redis_ok"] is True


@pytest.mark.asyncio
async def test_health_ready_returns_503_when_db_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    async def _failing_execute(*args: object, **kwargs: object) -> None:
        raise OSError("DB unreachable")

    monkeypatch.setattr(AsyncSession, "execute", _failing_execute)
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["data"]["db_ok"] is False
    assert body["data"]["status"] == "degraded"


@pytest.mark.asyncio
async def test_health_ready_returns_503_when_redis_down(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import redis.exceptions
    from backend.core.redis import redis_rl

    async def _failing_ping() -> bool:
        raise redis.exceptions.ConnectionError("Redis unreachable")

    monkeypatch.setattr(redis_rl, "ping", _failing_ping)
    r = await client.get("/api/v1/health/ready")
    assert r.status_code == 503
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"
    assert body["data"]["redis_ok"] is False
    assert body["data"]["status"] == "degraded"
