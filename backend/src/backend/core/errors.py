"""Application error definitions and exception handlers."""

from __future__ import annotations

import logging

import redis.exceptions
import sqlalchemy as sa
from fastapi.responses import JSONResponse
from starlette.requests import Request

from backend.core.middleware import internal_error_response
from swarnbharat_shared.common import ErrorCode, ErrorDetail, ErrorResponse

logger = logging.getLogger(__name__)

RETRY_AFTER_SERVICE_UNAVAILABLE = "5"

CENTRAL_CONNECTIVITY_EXCEPTIONS = (
    redis.exceptions.ConnectionError,
    redis.exceptions.TimeoutError,
    redis.exceptions.BusyLoadingError,
    ConnectionError,
    TimeoutError,
    sa.exc.OperationalError,
    sa.exc.InterfaceError,
)


class ApiError(Exception):
    """Base exception for application-level API errors."""

    def __init__(
        self,
        status_code: int,
        code: ErrorCode,
        message: str,
        headers: dict[str, str] | None = None,
        field: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.headers = headers
        self.field = field


async def api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
    """Handle application ApiError by serializing to ErrorResponse envelope."""
    error = ErrorDetail(
        code=exc.code,
        message=exc.message,
        field=exc.field,
    )
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=error).model_dump(mode="json"),
        headers=exc.headers,
    )


async def central_connectivity_error_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle downstream connectivity drops with 503 envelope and Retry-After."""
    if isinstance(exc, (sa.exc.OperationalError, sa.exc.InterfaceError)):
        pass
    elif isinstance(exc, sa.exc.DBAPIError) and not getattr(exc, "connection_invalidated", False):
        if not request.scope.get("_error_logged"):
            request.scope["_error_logged"] = True
            logger.exception("Database driver error (not invalidated connection): %s", exc)
        return internal_error_response()

    logger.warning("Downstream dependency connectivity drop: %s", type(exc).__name__)
    error = ErrorDetail(
        code=ErrorCode.SERVICE_UNAVAILABLE,
        message="Downstream service temporarily unavailable",
    )
    return JSONResponse(
        status_code=503,
        content=ErrorResponse(error=error).model_dump(mode="json"),
        headers={"Retry-After": RETRY_AFTER_SERVICE_UNAVAILABLE},
    )
