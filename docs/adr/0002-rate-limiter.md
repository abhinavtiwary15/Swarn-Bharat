# ADR 0002: Custom Fixed-Window Redis Rate Limiter

## Status
Accepted

## Context
Standard third-party rate limiters like `fastapi-limiter` introduced API incompatibilities and implicitly trusted `X-Forwarded-For` headers without reverse proxy validation.

## Decision
Implement a custom fixed-window rate limiter directly on Redis:
- Windows are keyed as `rl:{path}:{client_ip}:{window_index}`.
- Real client IP is derived from `request.client.host`, populated securely by Uvicorn reverse proxy flags.
- Atomic Redis pipeline executes `INCR` and `EXPIRE`.
- If Redis is unavailable, the limiter fails closed with HTTP 503 (`RATE_LIMITER_UNAVAILABLE`) and a `Retry-After` header.
- Limit violations return HTTP 429 (`RATE_LIMIT_EXCEEDED`) with a calculated `Retry-After` header.

## Consequences
No untrusted header spoofing. Predictable failure modes and zero dependencies on fragile third-party limiter packages.
