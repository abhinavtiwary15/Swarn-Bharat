# Auth behaviour specification (Stage B2)

This document and `openapi.json` are the only inputs for the black-box integration
tests under `backend/tests/integration/`. Where the two disagree, report it; do not
guess.

## 1. Conventions

- Base path `/api/v1`. JSON request and response bodies.
- Success body: `{"success": true, "data": <payload>, "error": null}`.
- Error body: `{"success": false, "data": null, "error": {"code": <ErrorCode>, "message": <string>, "field": <string|null>}}`.
  Tests assert HTTP status and `error.code`. Messages are not part of the contract,
  except that two responses documented as identical must have identical bodies.
- Authentication: `Authorization: Bearer <access_token>`. No cookies.
- Validation failures: 422, `VALIDATION_ERROR`, `field` names the first failing field.
- `Retry-After` is an integer number of seconds, at least 1.

## 2. Default parameters

These come from settings and are printed in the OpenAPI description. Tests use the
defaults and must not assume other values.

| Parameter | Default |
|---|---|
| Access token lifetime | 15 minutes (`expires_in: 900`) |
| Refresh token lifetime | 7 days |
| Refresh grace window | 30 seconds |
| Per-IP limit, login | 5 requests per 60 s |
| Per-IP limit, register | 5 requests per 60 s |
| Per-IP limit, refresh | 30 requests per 60 s |
| Per-IP limit, logout | 30 requests per 60 s |
| Account lockout | 10 failed attempts per email in a fixed 900 s window |

## 3. Token semantics

- Access token: JWT with claims `sub` (user id), `type` = `access`, `iat`, `exp`.
- Refresh token: JWT with claims `sub`, `type` = `refresh`, `jti`, `iat`, `exp`.
- The two types use different signing keys. A token of one type is never accepted
  where the other is expected.
- Refresh tokens are single use. A successful refresh returns a new refresh token
  with a new `jti` and invalidates the presented one.
- Grace window: presenting a refresh token again within the grace window after it
  was rotated succeeds and returns a refresh token carrying the same `jti` as the
  first successor. No second session is created.
- Reuse: presenting a rotated refresh token after the grace window is a replay.
  The response is 401 `TOKEN_REUSE_DETECTED` and every refresh token of that user
  becomes invalid; afterwards each of them yields 401 `SESSION_REVOKED`.
- Replaying a rotated token within the grace window after the successor was revoked
  (logout or revoke-all) yields 401 `SESSION_REVOKED`, not a new token.
- Access tokens are stateless. Logout and revocation do not invalidate an access
  token before its `exp`.

## 4. POST /auth/register

Request: `email` (valid address, at most 254 characters), `password` (8 to 128
characters), `full_name` (1 to 200 characters after trimming; whitespace-only is
rejected).

Rules:
- Email comparison is case-insensitive. `A@x.com` and `a@x.com` are the same account.
  The returned `email` is lowercase. Surrounding whitespace is ignored.
- No tokens are issued.

| Status | Code | When |
|---|---|---|
| 201 | none | Created. `data`: `id`, `email`, `full_name` (trimmed), `is_verified` = false, `oauth_provider` = null, `created_at`. No password or hash anywhere. |
| 409 | `EMAIL_TAKEN` (`field` = `email`) | Email already registered, including case variants. |
| 422 | `VALIDATION_ERROR` | Any bound or format violation. |
| 429 | `RATE_LIMIT_EXCEEDED` | Per-IP limit; `Retry-After` present. |
| 503 | `SERVICE_UNAVAILABLE` or `RATE_LIMITER_UNAVAILABLE` | Dependency outage; `Retry-After` present. |

Concurrent registration of one email: exactly one 201, all others 409.

## 5. POST /auth/login

Request: `email` (at most 254), `password` (1 to 128 characters). Email is
case-insensitive.

| Status | Code | When |
|---|---|---|
| 200 | none | `data`: `access_token`, `refresh_token`, `token_type` = `bearer`, `expires_in` = 900. Headers `Cache-Control: no-store`, `Pragma: no-cache`. The failure counter for the email is cleared. |
| 401 | `INVALID_CREDENTIALS` | Wrong password or unknown email. The two cases return identical status and body. |
| 422 | `VALIDATION_ERROR` | Bound or format violation. |
| 429 | `ACCOUNT_LOCKED` | See lockout rules; `Retry-After` present. |
| 429 | `RATE_LIMIT_EXCEEDED` | Per-IP limit; `Retry-After` present. |
| 503 | `SERVICE_UNAVAILABLE` or `RATE_LIMITER_UNAVAILABLE` | Dependency outage; `Retry-After` present. |

Lockout rules:
- Every login attempt for a normalized email counts toward a fixed window that starts
  with the first attempt and lasts 900 seconds. The window is not extended by later
  attempts.
- Attempts 1 to 10 in a window are evaluated normally. A wrong password returns 401.
- Attempt 11 and later in the same window return 429 `ACCOUNT_LOCKED` before any
  password check, even when the password is correct. `Retry-After` equals the
  remaining time of the window.
- Unknown emails are counted and locked exactly like known ones. A locked response
  must not reveal whether the account exists.
- A successful login clears the counter.
- Under concurrency, at most 10 password checks run per window.
- The per-IP limit (5 per 60 s) applies independently. From a single IP it triggers
  before the 10-attempt lockout. Tests may flush the rate-limit Redis database
  between requests to exercise the lockout.

## 6. POST /auth/refresh

Request: `refresh_token` (1 to 2048 characters).

| Status | Code | When |
|---|---|---|
| 200 | none | New token pair (same shape and headers as login). Also returned for a replay inside the grace window. |
| 401 | `TOKEN_INVALID` | Tampered or unparseable token, wrong token type (for example an access token), or a non-UUID `sub`. |
| 401 | `TOKEN_EXPIRED` | Correctly signed refresh token past its `exp`. |
| 401 | `SESSION_REVOKED` | Token unknown, logged out, or revoked. |
| 401 | `TOKEN_REUSE_DETECTED` | Replay after the grace window; all sessions of the user are revoked. |
| 401 | `UNAUTHORIZED` | The user no longer exists; the user's sessions are revoked. |
| 422 | `VALIDATION_ERROR` | Missing or oversized token. |
| 429 | `RATE_LIMIT_EXCEEDED` | Per-IP limit; `Retry-After` present. |
| 503 | `SERVICE_UNAVAILABLE` or `RATE_LIMITER_UNAVAILABLE` | Dependency outage; `Retry-After` present. |

There is no 404 on this endpoint. 401 responses carry no `WWW-Authenticate` header
because the token travels in the body.

## 7. POST /auth/logout

Request: `refresh_token` (1 to 2048 characters).

| Status | Code | When |
|---|---|---|
| 200 | none | `data`: `{"status": "ok"}`. The presented token's session is revoked. |
| 401 | `TOKEN_INVALID` | Tampered or unparseable token, or wrong token type. |
| 422 | `VALIDATION_ERROR` | Missing or oversized token. |
| 429 | `RATE_LIMIT_EXCEEDED` | Per-IP limit; `Retry-After` present. |
| 503 | `SERVICE_UNAVAILABLE` or `RATE_LIMITER_UNAVAILABLE` | Dependency outage; `Retry-After` present. |

Rules:
- Idempotent: logging out the same token twice returns 200 both times. A correctly
  signed but expired refresh token also returns 200.
- Only the presented `jti` is revoked. Other sessions of the same user keep working.
  Presenting a token that has already been rotated away does not end its successor.
- After logout, refreshing with that token returns 401 `SESSION_REVOKED`, and an
  already issued access token still works on `/auth/me` until it expires.

## 8. GET /auth/me

| Status | Code | When |
|---|---|---|
| 200 | none | `data`: the same user object as registration. |
| 401 | `UNAUTHORIZED` | Header missing, empty, or not a Bearer scheme; or the user no longer exists. |
| 401 | `TOKEN_INVALID` | Tampered token, or a refresh token used as an access token. |
| 401 | `TOKEN_EXPIRED` | Correctly signed access token past its `exp`. |
| 503 | `SERVICE_UNAVAILABLE` | Database outage; `Retry-After` present. |

Every 401 from this endpoint carries a `WWW-Authenticate` header that starts with
`Bearer`.

## 9. Cross-cutting

- Every error response uses the error body from section 1, including 404, 405, 422
  and 500.
- With an `Origin` listed in the CORS settings, error responses also carry
  `Access-Control-Allow-Origin`.
- Dependency outages are covered by unit tests. Integration tests are not required to
  simulate them.

## 10. Test environment

- Real Postgres (the `_test` database) and Redis. Test Redis databases are 12 (tokens),
  13 (rate limiter) and 14 (login throttle). Flush them between tests.
- Use unique emails per test. Do not depend on test order.
- Avoid wall-clock sleeps. For grace-window expiry, at most one test may set
  `REFRESH_GRACE_WINDOW_SECONDS=1` and wait a bounded 3 seconds. Other time-dependent
  cases (expired tokens) are built by signing tokens with the test environment's keys.
- Out of scope: Google sign-in, email verification, password reset, logout-all.
