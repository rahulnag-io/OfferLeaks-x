"""Refresh-token session store, backed by Redis.

Refresh tokens are JWTs (self-contained, statelessly verifiable), but
rotation and revocation need *some* server-side state -- otherwise a
stolen refresh token stays valid until it naturally expires, and "log
out everywhere" is impossible. Redis holding the set of currently-valid
refresh-token `jti`s (TTL'd to match the token's own expiry) is exactly
the "session/rate-limit store" role architecture.md §0.4 assigns it,
so this reuses that existing infrastructure rather than adding a new
Postgres table for something this operationally simple.

On each refresh: the presented jti must exist in Redis (else the refresh
token has already been used/revoked/expired -> reject), it's deleted, and
a new jti is stored for the freshly-issued refresh token. This is refresh
token rotation with reuse detection.
"""

import uuid
from datetime import UTC, datetime

from redis.asyncio import Redis

_KEY_PREFIX = "auth:refresh_session:"


def _key(jti: str) -> str:
    return f"{_KEY_PREFIX}{jti}"


async def store_refresh_session(
    redis: Redis, *, jti: str, user_id: uuid.UUID, expires_at: datetime
) -> None:
    ttl_seconds = max(1, int((expires_at - datetime.now(UTC)).total_seconds()))
    await redis.set(_key(jti), str(user_id), ex=ttl_seconds)


async def is_refresh_session_valid(redis: Redis, *, jti: str, user_id: uuid.UUID) -> bool:
    stored_user_id = await redis.get(_key(jti))
    return stored_user_id is not None and stored_user_id == str(user_id)


async def revoke_refresh_session(redis: Redis, *, jti: str) -> None:
    await redis.delete(_key(jti))
