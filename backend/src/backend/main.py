"""FastAPI application factory and middleware configuration."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi import HTTPException as FastAPIHTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.httpsredirect import HTTPSRedirectMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.requests import Request
from swarnbharat_shared.common import ErrorCode, ErrorDetail, ErrorResponse

from backend.api.v1.router import v1_router
from backend.core.config import settings
from backend.core.middleware import AppSafetyMiddleware, internal_error_response
from backend.core.redis import close_all

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage application startup and shutdown lifecycle."""
    yield
    await close_all()


def _make_operation_id(route: APIRoute) -> str:
    """Produce stable, readable operation IDs: {tag}-{handler_name}."""
    tag = str(route.tags[0]).lower().replace(" ", "-") if route.tags else "api"
    name = route.name.replace("_", "-")
    return f"{tag}-{name}"


app = FastAPI(
    title=settings.API_TITLE,
    version=settings.API_VERSION,
    description=settings.API_DESCRIPTION,
    openapi_url=settings.OPENAPI_URL,
    docs_url=settings.API_DOCS_URL,
    redoc_url=settings.API_REDOC_URL,
    lifespan=lifespan,
    generate_unique_id_function=_make_operation_id,
)

app.add_middleware(AppSafetyMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
    expose_headers=["Retry-After"],
)

app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=settings.ALLOWED_HOSTS,
)

if settings.ENFORCE_HTTPS:
    app.add_middleware(HTTPSRedirectMiddleware)


_STATUS_CODES: dict[int, str] = {
    400: ErrorCode.BAD_REQUEST,
    401: ErrorCode.UNAUTHORIZED,
    403: ErrorCode.FORBIDDEN,
    404: ErrorCode.NOT_FOUND,
    405: ErrorCode.METHOD_NOT_ALLOWED,
    409: ErrorCode.CONFLICT,
    429: ErrorCode.RATE_LIMIT_EXCEEDED,
}


def _build_http_response(exc: StarletteHTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict):
        error = ErrorDetail(**exc.detail)
    else:
        code = _STATUS_CODES.get(exc.status_code, ErrorCode.HTTP_ERROR)
        error = ErrorDetail(code=code, message=str(exc.detail))
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(error=error).model_dump(mode="json"),
        headers=dict(exc.headers or {}),
    )


@app.exception_handler(StarletteHTTPException)
async def starlette_http_exc_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
    """Handle Starlette HTTP routing exceptions."""
    return _build_http_response(exc)


@app.exception_handler(FastAPIHTTPException)
async def fastapi_http_exc_handler(request: Request, exc: FastAPIHTTPException) -> JSONResponse:
    """Handle application HTTP exceptions."""
    return _build_http_response(exc)


@app.exception_handler(RequestValidationError)
async def validation_exc_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """Handle request schema validation errors."""
    errors = exc.errors()
    first = errors[0] if errors else {}
    loc = first.get("loc", ())
    field = ".".join(str(p) for p in loc[1:]) or None
    error = ErrorDetail(
        code=ErrorCode.VALIDATION_ERROR,
        message=first.get("msg", "Request validation failed"),
        field=field,
    )
    return JSONResponse(
        status_code=422,
        content=ErrorResponse(error=error).model_dump(mode="json"),
    )


@app.exception_handler(Exception)
async def catch_all_exc_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle uncaught exceptions with a sanitized 500 envelope."""
    if not request.scope.get("_error_logged"):
        request.scope["_error_logged"] = True
        logger.exception("Unhandled exception: %s %s", request.method, request.url.path)
    return internal_error_response()


app.include_router(v1_router, prefix="/api/v1")
