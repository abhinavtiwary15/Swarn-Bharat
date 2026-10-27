"""Fixed-window rate limiter using Redis."""

from __future__ import annotations

import logging
import math
import time
from collections.abc import Awaitable, Callable
from typing import Any

import redis.exceptions
from fastapi import HTTPException, Request
from swarnbharat_shared.common import ErrorCode

from backend.core.redis import redis_rl

logger = logging.getLogger(__name__)

RETRY_AFTER_UNAVAILABLE = "5"


def fixed_window(
    times: int,
    seconds: int,
) -> Callable[[Request], Awaitable[None]]:
    """Return a FastAPI dependency enforcing a fixed-window rate limit."""

    async def _check(request: Request) -> None:
        # Fallback to 'unknown' if client connection info is not available on the request.
        ip = request.client.host if request.client else "unknown"
        path = request.url.path
        window = int(time.time()) // seconds
        key = f"rl:{path}:{ip}:{window}"

        try:
            async with redis_rl.pipeline(transaction=True) as pipe:
                pipe.incr(key)
                # Refresh TTL on each hit to prevent eviction before the window boundary elapses.
                pipe.expire(key, seconds * 2)
                results: list[Any] = await pipe.execute()
        except redis.exceptions.RedisError as exc:
            logger.error("Rate limiter Redis failure: %s", exc)
            raise HTTPException(
                status_code=503,
                detail={
                    "code": ErrorCode.RATE_LIMITER_UNAVAILABLE,
                    "message": "Rate limiter is temporarily unavailable.",
                },
                headers={"Retry-After": RETRY_AFTER_UNAVAILABLE},
            ) from exc

        count: int = results[0]
        if count > times:
            window_end = (window + 1) * seconds
            retry_after = max(math.ceil(window_end - time.time()), 1)
            raise HTTPException(
                status_code=429,
                detail={
                    "code": ErrorCode.RATE_LIMIT_EXCEEDED,
                    "message": "Too many requests.",
                },
                headers={"Retry-After": str(retry_after)},
            )

        return None

    return _check
