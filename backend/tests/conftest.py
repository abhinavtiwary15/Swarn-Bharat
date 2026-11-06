"""Pytest configuration, fixtures, and test-only route registration."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx
import pytest
import pytest_asyncio
import redis.exceptions
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.responses import StreamingResponse

from backend.core.config import settings
from backend.core.database import engine
from backend.core.errors import ApiError
from backend.core.rate_limit import fixed_window
from backend.main import create_app
from swarnbharat_shared.common import ErrorCode


class _RequiredBody(BaseModel):
    required_field: str


_test_router = APIRouter(prefix="/_test", include_in_schema=False)


@_test_router.post("/validate")
async def _validate_body(_body: _RequiredBody) -> dict[str, bool]:
    return {"ok": True}


@_test_router.get("/boom")
async def _trigger_500() -> None:
    raise RuntimeError("forced 500 for testing")


@_test_router.get("/api-error")
async def _trigger_api_error() -> None:
    raise ApiError(
        status_code=400,
        code=ErrorCode.BAD_REQUEST,
        message="Explicit API error",
        field="test_field",
        headers={"X-Test-Header": "value"},
    )


@_test_router.get("/other")
async def _other_endpoint() -> dict[str, bool]:
    return {"ok": True}


@_test_router.get(
    "/rate-limited",
    dependencies=[Depends(fixed_window(times=2, seconds=60))],
)
async def _rate_limited_endpoint() -> dict[str, bool]:
    return {"ok": True}


async def _failing_stream() -> AsyncIterator[bytes]:
    yield b"start"
    raise RuntimeError("stream failure after start")


@_test_router.get("/started-fail")
async def _started_fail() -> StreamingResponse:
    return StreamingResponse(_failing_stream())


@_test_router.get("/db-operational-error")
async def _trigger_db_op_error() -> None:
    raise sa.exc.OperationalError("db op error", {}, Exception())


@_test_router.get("/redis-connection-error")
async def _trigger_redis_conn_error() -> None:
    raise redis.exceptions.ConnectionError("redis conn down")


@_test_router.get("/dbapi-invalidated")
async def _trigger_dbapi_invalidated() -> None:
    raise sa.exc.DBAPIError("stmt", {}, Exception(), connection_invalidated=True)


@_test_router.get("/dbapi-not-invalidated")
async def _trigger_dbapi_not_invalidated() -> None:
    raise sa.exc.DBAPIError("stmt", {}, Exception(), connection_invalidated=False)


@_test_router.get("/redis-response-error")
async def _trigger_redis_response_error() -> None:
    raise redis.exceptions.ResponseError("bad syntax")


@_test_router.get("/os-error")
async def _trigger_os_error() -> None:
    raise OSError("disk error")


def create_test_app() -> FastAPI:
    """Build a dedicated FastAPI instance with test routes mounted."""
    test_app = create_app()
    test_app.include_router(_test_router)
    return test_app


_DEV_REDIS_DBS = {2, 3, 4}


@pytest.fixture(scope="session", autouse=True)
def _guard_test_environment() -> None:
    """Assert this is a safe test environment before any test runs."""
    assert settings.APP_ENV == "test", (
        f"APP_ENV must be 'test', got {settings.APP_ENV!r}. "
        "This is set automatically by pytest-env — do not override it in .env."
    )

    db_name = settings.DATABASE_URL.split("/")[-1].split("?")[0]
    assert db_name.endswith("_test"), (
        f"DATABASE_URL must point to a database ending with '_test', got {db_name!r}. "
        "Update DATABASE_URL in your environment or let pytest-env supply the default."
    )

    for attr, dev_val in [
        ("REDIS_DB_TOKENS", 2),
        ("REDIS_DB_RATE_LIMIT", 3),
        ("REDIS_DB_LOGIN_THROTTLE", 4),
    ]:
        val: int = getattr(settings, attr)
        assert val not in _DEV_REDIS_DBS, (
            f"{attr}={val} overlaps with a dev Redis DB ({dev_val}). "
            "Use dedicated test indexes (12, 13, 14) set in [tool.pytest.ini_options] env."
        )


@pytest_asyncio.fixture(scope="session")
async def managed_app() -> AsyncIterator[FastAPI]:
    """Run FastAPI lifecycle once for integration tests."""
    try:
        async with engine.connect() as conn:
            await conn.execute(sa.text("SELECT 1"))
    except (OSError, sa.exc.SQLAlchemyError) as exc:
        db_name = settings.DATABASE_URL.split("/")[-1].split("?")[0]
        pytest.fail(
            f"\n[TEST ENVIRONMENT ERROR] Test database {db_name!r} is not accessible.\n"
            f"Run 'uv run python scripts/prepare_test_db.py' to create and migrate it.\n"
            f"Error details: {type(exc).__name__}: {exc}"
        )

    test_app = create_test_app()
    async with LifespanManager(test_app):
        yield test_app


@pytest_asyncio.fixture
async def clean_tables() -> AsyncIterator[None]:
    """Truncate tables between integration test runs."""
    yield
    async with engine.begin() as conn:
        await conn.execute(sa.text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """Provide an async database session for tests and truncate users after each test."""
    from backend.core.database import _SessionLocal

    async with _SessionLocal() as session:
        yield session
    async with engine.begin() as conn:
        await conn.execute(sa.text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture
async def flush_redis() -> AsyncIterator[None]:
    """Flush test Redis databases between integration test runs."""
    from backend.core.redis import redis_rl, redis_throttle, redis_tokens

    for r in (redis_tokens, redis_rl, redis_throttle):
        await r.flushdb()
    yield


@pytest_asyncio.fixture
async def client(
    managed_app: FastAPI,
    clean_tables: None,
    flush_redis: None,
) -> AsyncIterator[httpx.AsyncClient]:
    """Provide a test HTTP client bound to the application for integration tests."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=managed_app),
        base_url="http://localhost",
    ) as c:
        yield c


@pytest.fixture
def app_settings() -> Any:
    """Provide settings instance for test configuration overrides."""
    return settings


@pytest.fixture
def make_client(managed_app: FastAPI) -> Callable[[str], httpx.AsyncClient]:
    """Factory to create httpx.AsyncClient with a specific client IP for rate-limit / lockout tests."""

    def _builder(client_ip: str = "127.0.0.1") -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=managed_app, client=(client_ip, 12345)),
            base_url="http://localhost",
        )

    return _builder


@pytest.fixture
def redis_tokens_client() -> Any:
    """Provide direct access to test Redis DB 12 (tokens)."""
    from backend.core.redis import redis_tokens

    return redis_tokens


@pytest.fixture
def redis_rl_client() -> Any:
    """Provide direct access to test Redis DB 13 (rate limiter)."""
    from backend.core.redis import redis_rl

    return redis_rl


@pytest.fixture
def redis_throttle_client() -> Any:
    """Provide direct access to test Redis DB 14 (login throttle)."""
    from backend.core.redis import redis_throttle

    return redis_throttle


@pytest.fixture
def make_access_token() -> Callable[..., str]:
    """Factory fixture to mint JWT access tokens for black-box testing (docs/specs/auth-b2.md §3 & §10)."""
    import time
    from uuid import uuid4

    import jwt

    def _maker(
        sub: str | None = None,
        exp_delta: int = 900,
        token_type: str = "access",
        key: str = settings.JWT_SECRET_KEY,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": str(uuid4()) if sub is None else sub,
            "type": token_type,
            "iat": now,
            "exp": now + exp_delta,
        }
        if extra_claims:
            claims.update(extra_claims)
        return jwt.encode(claims, key, algorithm="HS256")

    return _maker


@pytest.fixture
def make_refresh_token() -> Callable[..., str]:
    """Factory fixture to mint JWT refresh tokens for black-box testing (docs/specs/auth-b2.md §3 & §10)."""
    import time
    from uuid import uuid4

    import jwt

    def _maker(
        sub: str | None = None,
        jti: str | None = None,
        exp_delta: int = 604800,
        token_type: str = "refresh",
        key: str = settings.JWT_REFRESH_SECRET_KEY,
        extra_claims: dict[str, Any] | None = None,
    ) -> str:
        now = int(time.time())
        claims: dict[str, Any] = {
            "sub": str(uuid4()) if sub is None else sub,
            "type": token_type,
            "jti": str(uuid4()) if jti is None else jti,
            "iat": now,
            "exp": now + exp_delta,
        }
        if extra_claims:
            claims.update(extra_claims)
        return jwt.encode(claims, key, algorithm="HS256")

    return _maker
