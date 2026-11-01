"""Tests for central downstream connectivity error handler."""

from __future__ import annotations

import httpx
import pytest

from backend.core.errors import RETRY_AFTER_SERVICE_UNAVAILABLE


@pytest.mark.asyncio
async def test_db_operational_error_returns_503(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/db-operational-error")
    assert response.status_code == 503
    assert response.headers["retry-after"] == RETRY_AFTER_SERVICE_UNAVAILABLE
    body = response.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_redis_connection_error_returns_503(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/redis-connection-error")
    assert response.status_code == 503
    assert response.headers["retry-after"] == RETRY_AFTER_SERVICE_UNAVAILABLE
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_dbapi_invalidated_returns_503(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/dbapi-invalidated")
    assert response.status_code == 503
    assert response.headers["retry-after"] == RETRY_AFTER_SERVICE_UNAVAILABLE
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "SERVICE_UNAVAILABLE"


@pytest.mark.asyncio
async def test_dbapi_not_invalidated_returns_500(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/dbapi-not-invalidated")
    assert response.status_code == 500
    assert "retry-after" not in response.headers
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"


@pytest.mark.asyncio
async def test_redis_response_error_returns_500(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/redis-response-error")
    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"


@pytest.mark.asyncio
async def test_os_error_returns_500(client: httpx.AsyncClient) -> None:
    response = await client.get("/_test/os-error")
    assert response.status_code == 500
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
