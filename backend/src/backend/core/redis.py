"""Redis connection pools configured per logical purpose."""

from __future__ import annotations

import redis.asyncio as aioredis

from backend.core.config import settings


def _client(db: int) -> aioredis.Redis:
    pool = aioredis.ConnectionPool.from_url(
        settings.redis_url(db),
        decode_responses=True,
    )
    return aioredis.Redis(connection_pool=pool)


redis_tokens: aioredis.Redis = _client(settings.REDIS_DB_TOKENS)
redis_rl: aioredis.Redis = _client(settings.REDIS_DB_RATE_LIMIT)
redis_throttle: aioredis.Redis = _client(settings.REDIS_DB_LOGIN_THROTTLE)


async def close_all() -> None:
    """Close all Redis connection pools during application shutdown."""
    for r in (redis_tokens, redis_rl, redis_throttle):
        await r.aclose(close_connection_pool=True)
