"""Pure-ASGI HTTP middleware components."""

from __future__ import annotations

import logging

from starlette.datastructures import MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from backend.core.config import settings
from swarnbharat_shared.common import ErrorCode, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

HSTS_HEADER_VALUE = "max-age=31536000; includeSubDomains"


def internal_error_response() -> JSONResponse:
    """Build a standard 500 Internal Server Error envelope."""
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error=ErrorDetail(
                code=ErrorCode.INTERNAL_SERVER_ERROR,
                message="An unexpected error occurred.",
            )
        ).model_dump(mode="json"),
    )


class AppSafetyMiddleware:
    """Pure ASGI middleware for safety, error envelopes, and security headers."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        response_started = False

        async def send_wrapper(message: Message) -> None:
            nonlocal response_started
            if message["type"] == "http.response.start":
                response_started = True
                if settings.ENFORCE_HTTPS:
                    headers = MutableHeaders(scope=message)
                    headers["strict-transport-security"] = HSTS_HEADER_VALUE
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            scope["_error_logged"] = True
            logger.exception(
                "Unhandled exception: %s %s",
                scope.get("method"),
                scope.get("path"),
            )
            if response_started:
                raise

            err_resp = internal_error_response()
            await err_resp(scope, receive, send_wrapper)
