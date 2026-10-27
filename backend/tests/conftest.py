"""Pytest configuration, fixtures, and test-only route registration."""

from __future__ import annotations

from collections.abc import AsyncIterator

import httpx
import pytest
import pytest_asyncio
import sqlalchemy as sa
from asgi_lifespan import LifespanManager
from backend.core.config import settings
from backend.core.database import engine
from backend.core.rate_limit import fixed_window
from backend.main import app
from fastapi import APIRouter, Depends, FastAPI
from pydantic import BaseModel
from starlette.responses import StreamingResponse


class _RequiredBody(BaseModel):
    required_field: str


_test_router = APIRouter(prefix="/_test", include_in_schema=False)


@_test_router.post("/validate")
async def _validate_body(_body: _RequiredBody) -> dict[str, bool]:
    return {"ok": True}


@_test_router.get("/boom")
async def _trigger_500() -> None:
    raise RuntimeError("forced 500 for testing")


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


app.include_router(_test_router)


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
    """Run FastAPI lifecycle once for the test session."""
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

    async with LifespanManager(app):
        yield app


@pytest_asyncio.fixture
async def client(managed_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    """Provide a test HTTP client bound to the application."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=managed_app),
        base_url="http://localhost",
    ) as c:
        yield c


@pytest_asyncio.fixture(autouse=True)
async def clean_tables() -> AsyncIterator[None]:
    """Truncate tables after each test run."""
    yield
    async with engine.begin() as conn:
        await conn.execute(sa.text("TRUNCATE TABLE users RESTART IDENTITY CASCADE"))


@pytest_asyncio.fixture(autouse=True)
async def flush_redis() -> AsyncIterator[None]:
    """Flush test Redis databases after each test run."""
    from backend.core.redis import redis_rl, redis_throttle, redis_tokens

    for r in (redis_tokens, redis_rl, redis_throttle):
        await r.flushdb()
    yield
