"""Tests for Strict-Transport-Security (HSTS) middleware."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from starlette.types import Message, Receive, Scope, Send

from backend.core.config import settings
from backend.core.middleware import HSTS_HEADER_VALUE, AppSafetyMiddleware


async def test_hsts_header_present_when_enforce_https(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENFORCE_HTTPS", True)
    r = await client.get("/_test/other")
    assert r.status_code == 200
    assert r.headers.get("strict-transport-security") == HSTS_HEADER_VALUE


async def test_hsts_header_absent_when_not_enforce_https(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENFORCE_HTTPS", False)
    r = await client.get("/_test/other")
    assert r.status_code == 200
    assert "strict-transport-security" not in r.headers


async def test_other_response_headers_preserved_with_enforce_https(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(settings, "ENFORCE_HTTPS", True)
    origin = "http://localhost:3000"
    r = await client.get("/_test/api-error", headers={"Origin": origin})
    assert r.status_code == 400
    # Custom endpoint header preserved
    assert r.headers.get("x-test-header") == "value"
    # Content-type preserved
    assert "application/json" in r.headers.get("content-type", "")
    # CORS header preserved
    assert r.headers.get("access-control-allow-origin") == origin
    # HSTS header added
    assert r.headers.get("strict-transport-security") == HSTS_HEADER_VALUE


async def test_hsts_guard_message_without_headers(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "ENFORCE_HTTPS", True)

    async def _raw_app(scope: Scope, receive: Receive, send: Send) -> None:
        # Send http.response.start without 'headers' key in the message dictionary
        await send({"type": "http.response.start", "status": 204})
        await send({"type": "http.response.body", "body": b""})

    middleware = AppSafetyMiddleware(_raw_app)
    messages: list[Message] = []

    async def _send(msg: Message) -> None:
        messages.append(msg)

    async def _receive() -> Message:
        return {"type": "http.request"}

    scope: Scope = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": [],
    }

    await middleware(scope, _receive, _send)
    assert len(messages) >= 1
    start_msg = messages[0]
    assert start_msg["type"] == "http.response.start"
    assert "headers" in start_msg
    headers_dict = dict(start_msg["headers"])
    assert headers_dict.get(b"strict-transport-security") == HSTS_HEADER_VALUE.encode("latin-1")
