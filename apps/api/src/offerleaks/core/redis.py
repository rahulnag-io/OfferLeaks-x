"""Redis client management.

Redis backs three distinct concerns in this system (session/rate-limit
store, Celery/RQ broker, reputation-lookup cache -- see architecture.md
§0.4). Version 1 only needs a shared client and a liveness check; the
queue and cache usage patterns are added in the versions that need them.
"""

from redis.asyncio import Redis

from offerleaks.core.config import get_settings

settings = get_settings()

redis_client: Redis = Redis.from_url(settings.redis_url, decode_responses=True)


async def get_redis() -> Redis:
    """FastAPI dependency returning the shared Redis client."""
    return redis_client
