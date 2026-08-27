"""Redis-backed rate limiting.

A single reusable primitive (fixed-window counter per key) rather than a
per-endpoint bespoke implementation, per architecture.md §0.11 ("Redis-backed,
per-user and per-IP"). Version 2 applies it to the auth endpoints (per-IP
only -- there's no authenticated user yet at login time). Version 3's
upload endpoint has an authenticated caller, so it opts into `per_user=True`
to also key on the user id, per the Version 2 review's finding that a
general-purpose rate limiter reused by an authenticated endpoint should
support both.
"""

from collections.abc import Callable, Coroutine
from typing import Any

from fastapi import Depends, HTTPException, Request, status
from redis.asyncio import Redis

from offerleaks.core.redis import get_redis


async def _check_and_increment(
    redis: Redis, *, redis_key: str, max_attempts: int, window_seconds: int
) -> None:
    current = await redis.incr(redis_key)
    if current == 1:
        await redis.expire(redis_key, window_seconds)

    if current > max_attempts:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
        )


def rate_limit(
    *, key: str, max_attempts: int, window_seconds: int, per_user: bool = False
) -> Callable[..., Coroutine[Any, Any, None]]:
    """Build a FastAPI dependency enforcing `max_attempts` per `window_seconds`.

    Fixed-window counting: simple, cheap (one INCR + one EXPIRE-if-new),
    and precise enough for brute-force/abuse mitigation -- this doesn't
    need a sliding-window log's precision.

    Always limits per client IP. When `per_user=True`, a *second*,
    independent counter also limits per authenticated user id -- both
    must pass, so neither a single user rotating IPs nor many users
    sharing one IP (NAT, office wifi) can bypass the limit.
    """
    if not per_user:

        async def _ip_only_dependency(
            request: Request, redis: Redis = Depends(get_redis)
        ) -> None:
            client_ip = request.client.host if request.client else "unknown"
            await _check_and_increment(
                redis,
                redis_key=f"ratelimit:{key}:ip:{client_ip}",
                max_attempts=max_attempts,
                window_seconds=window_seconds,
            )

        return _ip_only_dependency

    # Deferred import: `auth.dependencies` sits above `core` in the
    # dependency graph (it imports `core.db`, `models`, `repositories`),
    # so importing it at module load time here would invert that
    # layering. Importing inside the factory function only when
    # `per_user=True` avoids that without restructuring either module.
    from offerleaks.auth.dependencies import get_current_user
    from offerleaks.models.user import User

    async def _ip_and_user_dependency(
        request: Request,
        redis: Redis = Depends(get_redis),
        user: User = Depends(get_current_user),
    ) -> None:
        client_ip = request.client.host if request.client else "unknown"
        await _check_and_increment(
            redis,
            redis_key=f"ratelimit:{key}:ip:{client_ip}",
            max_attempts=max_attempts,
            window_seconds=window_seconds,
        )
        await _check_and_increment(
            redis,
            redis_key=f"ratelimit:{key}:user:{user.id}",
            max_attempts=max_attempts,
            window_seconds=window_seconds,
        )

    return _ip_and_user_dependency
