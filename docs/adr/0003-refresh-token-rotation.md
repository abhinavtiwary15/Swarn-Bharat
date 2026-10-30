# ADR 0003: Refresh Token Rotation and Reuse Detection

## Status
Accepted

## Context
Long-lived refresh tokens present a high-value target for exfiltration. To mitigate persistent unauthorized access in the event of token compromise, tokens must be single-use and rotate upon every refresh exchange. However, mobile and distributed web clients frequently encounter intermittent network partitions or packet loss, leading to situations where a rotation request succeeds on the server but the client never receives the response. If the client retries with the same refresh token, strict single-use semantics would misinterpret this as a token replay attack and invalidate the user's active session.

## Decision
1. **Single-Use Rotation**: Refresh tokens are single-use JWTs containing an explicit `jti` claim, tracked in Redis (`tok:{jti}`).
2. **Grace Window**: When an active token is rotated via atomic Lua script, it enters a configurable grace window (default 30 seconds) in state `rotated:{new_jti}:{grace_until}`. Any subsequent rotation request using that same old token within the grace window returns the already-generated replacement `jti` instead of generating a new token family or raising an error.
3. **Session Set Tracking**: Active refresh tokens are tracked per user in a Redis set (`tok:user:{user_id}`) with rolling TTL matching the token expiry window.
4. **Theft & Reuse Invalidation**: If an already-rotated token is presented outside its grace window, the server detects token reuse. `rotate_token` immediately calls `revoke_all_for_user(user_id)` to invalidate every active session for that user across all devices before raising `TokenReuseError`.
5. **Targeted Logout**: Single-session logout (`revoke_token`) marks the specific token as `revoked` and removes it from `tok:user:{user_id}`, leaving other active device sessions intact without triggering reuse detection.

## Consequences
- **Grace Window Tradeoff**: The 30-second window permits idempotent retries during transient network failures without false-positive session logouts. The consequence is that a stolen old token replayed within the grace window after a legitimate rotation is not flagged and receives the successor; later replays outside the grace window trigger reuse detection and revoke all sessions for that user.
- **Blast Radius on Reuse**: When token reuse is detected, all sessions for that user across all devices are immediately revoked. This aggressively contains potential attacker compromise while requiring the legitimate user to re-authenticate with fresh credentials.
- **Single-Node Redis Dependency**: Key operations and dynamic keys within the rotation script rely on a standalone Redis instance with logical databases (ADR 0002).
