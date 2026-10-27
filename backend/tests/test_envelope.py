"""Tests for exception handler envelope consistency."""

from __future__ import annotations

import logging

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_404_uses_envelope(client: AsyncClient) -> None:
    r = await client.get("/api/v1/does-not-exist")
    assert r.status_code == 404
    body = r.json()
    assert body["success"] is False
    assert body["data"] is None
    assert body["error"]["code"] == "NOT_FOUND"
    assert body["error"]["message"]


@pytest.mark.asyncio
async def test_405_uses_envelope(client: AsyncClient) -> None:
    r = await client.delete("/api/v1/health/live")
    assert r.status_code == 405
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "METHOD_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_422_uses_envelope(client: AsyncClient) -> None:
    r = await client.post("/_test/validate", json={})
    assert r.status_code == 422
    body = r.json()
    assert body["success"] is False
    error = body["error"]
    assert error["code"] == "VALIDATION_ERROR"
    assert error["field"] is not None
    assert error["message"]


@pytest.mark.asyncio
async def test_api_error_uses_envelope(client: AsyncClient) -> None:
    r = await client.get("/_test/api-error")
    assert r.status_code == 400
    assert r.headers.get("x-test-header") == "value"
    body = r.json()
    assert body["success"] is False
    assert body["data"] is None
    error = body["error"]
    assert error["code"] == "BAD_REQUEST"
    assert error["message"] == "Explicit API error"
    assert error["field"] == "test_field"


@pytest.mark.asyncio
async def test_500_uses_envelope(client: AsyncClient) -> None:
    r = await client.get("/_test/boom")
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert "forced 500" not in body["error"]["message"]


@pytest.mark.asyncio
async def test_500_logs_exception(client: AsyncClient, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.ERROR):
        r = await client.get("/_test/boom")
    assert r.status_code == 500
    assert any("Unhandled exception" in record.message for record in caplog.records)


@pytest.mark.asyncio
async def test_500_cors_headers_preserved_on_exception(client: AsyncClient) -> None:
    origin = "http://localhost:3000"
    r = await client.get("/_test/boom", headers={"Origin": origin})
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    assert body["error"]["code"] == "INTERNAL_SERVER_ERROR"
    assert r.headers.get("access-control-allow-origin") == origin


@pytest.mark.asyncio
async def test_exception_after_response_started_is_reraised(client: AsyncClient) -> None:
    with pytest.raises(RuntimeError, match="stream failure after start"):
        await client.get("/_test/started-fail")
