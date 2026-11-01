# ADR 0004: Login Throttling, Lockout, and Anti-Enumeration Defense

## Status
Accepted

## Context
Authentication endpoints are susceptible to brute-force credential stuffing, timing side-channels, and distributed dictionary attacks. We require an account lockout mechanism that protects user accounts without allowing attackers to exhaustively enumerate registered emails or execute uncontrolled concurrent password hash operations.

## Decision

### 1. Redis Requirements
The lockout mechanism relies on atomic fixed-window expiration:
```redis
INCR login:fail:<sha256>
EXPIRE login:fail:<sha256> <seconds> NX
TTL login:fail:<sha256>
```
The `EXPIRE ... NX` option requires **Redis >= 7.0**. This guarantees a strict fixed-window lockout: the TTL is initialized on the first failed attempt and is never extended by subsequent attempts within that window.

### 2. Multi-Layer Rate Limiting Architecture
Protection is applied in two distinct, complementary layers:
- **Layer 1: Per-IP Rate Limiting (Network Flood Protection)**
  Enforced by standard sliding/fixed-window limiter across all requests from a client IP (`5 req / 60s` on `/auth/login`). This mitigates high-volume automated traffic and single-origin denial of service.
- **Layer 2: Per-Email Account Lockout (Distributed Brute-Force Protection)**
  Enforced per normalized email in Redis DB 4 (`redis_throttle`). Tracks failed attempts across arbitrary distributed IP addresses. Allows attempts 1–10 to verify credentials normally, while attempt 11 and later immediately return `429 ACCOUNT_LOCKED` with a dynamic `Retry-After` header matching the remaining TTL of the fixed window.

### 3. Concurrency Bounds on Password Hashing
Argon2id is deliberately computationally expensive. Without pre-verification throttling, a burst of parallel requests could saturate server CPU capacity. By executing `INCR` in Redis prior to password evaluation, the system bounds parallel password checks to at most 10 concurrent Argon2id verifications per target email per window. Once the counter exceeds 10, all subsequent requests are rejected immediately at 429 without invoking `verify_password`.

### 4. Anti-Enumeration & Timing Defense
- **Hashed Keys in Redis**: Email addresses are normalized (`strip().lower()`) and hashed via SHA-256 (`login:fail:{sha256}`) before storage in Redis DB 4 to avoid persisting plaintext PII in volatile memory.
- **Constant-Time Verification**: When an unknown email is supplied, `verify_password(password, None)` executes against a constant dummy hash off the event loop thread using `anyio.CapacityLimiter(4)`. Both non-existent users and wrong passwords return identical `401 INVALID_CREDENTIALS` responses and incur identical timing profiles.
- **Account Lockout on Non-Existent Users**: The failure counter increments and locks out unknown emails identically to registered emails, preventing attackers from discerning account existence via lockout behavior.

### 5. Email Enumeration Trade-Offs
- **Registration**: Registration returns `409 EMAIL_TAKEN` (`field="email"`) when an email already exists. This conscious UX trade-off provides immediate feedback during user sign-up rather than requiring opaque asynchronous email confirmation loops (deferred to Stage B3+).
- **Login**: Login strictly maintains anti-enumeration: responses for invalid passwords, unknown emails, and unverified accounts return an indistinguishable `401 INVALID_CREDENTIALS`.

## Design choices to confirm

1. **Email Uniqueness Discrimination**: Immediate `409 EMAIL_TAKEN` during registration is chosen over silent absorption for user onboarding clarity.
2. **Pre-Rotation User Existence Check**: `/refresh` verifies user existence in Postgres before rotating tokens in Redis. If the user was deleted, all user sessions are immediately revoked and `401 UNAUTHORIZED` is returned.
3. **Idempotent Expired Logout**: Logging out with an expired refresh token succeeds with `200 OK` (`{"status": "ok"}`), ensuring idempotent cleanup without revealing token expiration details.
