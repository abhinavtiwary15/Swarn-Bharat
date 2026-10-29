"""Refresh token storage, atomic rotation, and reuse detection service."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from backend.core.config import settings
from backend.core.redis import redis_tokens

logger = logging.getLogger(__name__)

# Atomic token rotation script.
# - Uses server-side TIME to prevent clock skew between app instances.
# - Distinguishes explicit logouts ("REVOKED") from replayed rotated tokens ("REUSE").
# - Within grace window, returns existing replacement jti for idempotent client recovery.
# - Atomically handles token keys and user-session set membership.
_ROTATION_LUA_SCRIPT = """
local old_key = KEYS[1]
local new_key = KEYS[2]
local user_key = KEYS[3]
local new_jti = ARGV[1]
local old_jti = ARGV[2]
local grace_window = tonumber(ARGV[3])
local refresh_ttl = tonumber(ARGV[4])

local time_res = redis.call("TIME")
local now = tonumber(time_res[1])

local old_val = redis.call("GET", old_key)

if not old_val then
    return "NOT_FOUND"
end

if old_val == "revoked" then
    return "REVOKED"
end

if old_val == "active" then
    local grace_until = now + grace_window
    local rotated_val = "rotated:" .. new_jti .. ":" .. tostring(grace_until)
    redis.call("SET", old_key, rotated_val, "EX", refresh_ttl)
    redis.call("SET", new_key, "active", "EX", refresh_ttl)
    redis.call("SREM", user_key, old_jti)
    redis.call("SADD", user_key, new_jti)
    redis.call("EXPIRE", user_key, refresh_ttl)
    return "OK"
end

if string.sub(old_val, 1, 8) == "rotated:" then
    local parts = {}
    for part in string.gmatch(string.sub(old_val, 9), "[^:]+") do
        table.insert(parts, part)
    end
    local replacement_jti = parts[1]
    local grace_until = tonumber(parts[2])

    if now < grace_until then
        return "GRACE:" .. replacement_jti
    else
        redis.call("SET", old_key, "revoked", "EX", refresh_ttl)
        -- Single-node Redis constraint: replacement_key ('tok:' .. replacement_jti) is dynamically
        -- constructed, valid on standalone Redis (ADR 0002) but not on Redis Cluster.
        if replacement_jti then
            redis.call("SET", "tok:" .. replacement_jti, "revoked", "EX", refresh_ttl)
        end
        return "REUSE"
    end
end

return "NOT_FOUND"
"""

_rotation_script = redis_tokens.register_script(_ROTATION_LUA_SCRIPT)

_REVOKE_ALL_LUA_SCRIPT = """
local user_key = KEYS[1]
local refresh_ttl = tonumber(ARGV[1])

local members = redis.call("SMEMBERS", user_key)
local count = #members

for i = 1, count do
    -- Single-node Redis constraint: session keys ('tok:' .. jti) are dynamically
    -- constructed, valid on standalone Redis (ADR 0002) but not on Redis Cluster.
    redis.call("SET", "tok:" .. members[i], "revoked", "EX", refresh_ttl)
end

redis.call("DEL", user_key)
return count
"""

_revoke_all_script = redis_tokens.register_script(_REVOKE_ALL_LUA_SCRIPT)


class TokenError(Exception):
    """Base exception for token operations."""


class TokenNotFoundError(TokenError):
    """Token jti not found or already logged out."""


class TokenReuseError(TokenError):
    """Token reuse detected outside grace window."""


@dataclass(frozen=True)
class RotationResult:
    status: Literal["ok", "grace"]
    jti: str


def _user_key(user_id: UUID | str) -> str:
    return f"tok:user:{user_id}"


async def record_issued_token(user_id: UUID | str, jti: str) -> None:
    """Store an active refresh token jti and record it in the user session set with rolling TTL."""
    ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    user_key = _user_key(user_id)
    pipe = redis_tokens.pipeline()
    pipe.set(f"tok:{jti}", "active", ex=ttl)
    pipe.sadd(user_key, jti)
    pipe.expire(user_key, ttl)
    await pipe.execute()


async def rotate_token(
    user_id: UUID | str,
    old_jti: str,
    new_jti: str,
    grace_window_seconds: int | None = None,
) -> RotationResult:
    """Atomically rotate a refresh token with grace window reuse detection (see ADR 0003)."""
    grace = (
        grace_window_seconds
        if grace_window_seconds is not None
        else settings.REFRESH_GRACE_WINDOW_SECONDS
    )
    ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400

    raw_res = await _rotation_script(
        keys=[f"tok:{old_jti}", f"tok:{new_jti}", _user_key(user_id)],
        args=[new_jti, old_jti, str(grace), str(ttl)],
    )
    result_str = str(raw_res)

    if result_str == "OK":
        return RotationResult(status="ok", jti=new_jti)

    if result_str.startswith("GRACE:"):
        replacement_jti = result_str.split(":", 1)[1]
        return RotationResult(status="grace", jti=replacement_jti)

    if result_str == "REUSE":
        logger.warning("Token reuse detected for jti %s, user %s", old_jti, user_id)
        await revoke_all_for_user(user_id)
        raise TokenReuseError(f"Refresh token reuse detected for jti {old_jti}")

    if result_str in ("NOT_FOUND", "REVOKED"):
        raise TokenNotFoundError(f"Refresh token {old_jti} not found or expired")

    raise TokenError(f"Unexpected rotation response: {result_str}")


async def revoke_token(user_id: UUID | str, jti: str) -> None:
    """Explicitly revoke a token jti for a user."""
    ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    user_key = _user_key(user_id)
    pipe = redis_tokens.pipeline()
    pipe.set(f"tok:{jti}", "revoked", ex=ttl)
    pipe.srem(user_key, jti)
    await pipe.execute()


async def revoke_all_for_user(user_id: UUID | str) -> int:
    """Revoke all active tokens for a user (called on token reuse or security reset)."""
    ttl = settings.REFRESH_TOKEN_EXPIRE_DAYS * 86400
    user_key = _user_key(user_id)
    raw_res = await _revoke_all_script(keys=[user_key], args=[str(ttl)])
    return int(raw_res)


async def is_token_active(jti: str) -> bool:
    """Check if token is active in Redis."""
    val: object = await redis_tokens.get(f"tok:{jti}")
    return val == "active"
