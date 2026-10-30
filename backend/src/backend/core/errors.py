"""Application error definitions and exception handler."""

from __future__ import annotations

from fastapi.responses import JSONResponse
from starlette.requests import Request

from swarnbharat_shared.common import ErrorCode, ErrorDetail, ErrorResponse


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
