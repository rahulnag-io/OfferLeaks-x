"""Background job queue (Redis-backed, per architecture.md §0.7/§0.8).

RQ, not Celery: a single job type (`process_analysis`), no need for
Celery's routing/scheduling machinery, and RQ's operational simplicity
matches the "MVP infra has to be low and boring" framing in §0.1. Chosen
over Celery as the smallest reasonable engineering decision for one job
type, not a rejection of Celery for anything more complex later.

RQ requires a *sync* `redis.Redis` client -- distinct from the async
client in `core/redis.py`, which FastAPI request handlers use. Enqueuing
from an async request handler is a fast, non-blocking Redis call in
practice, so this doesn't need its own thread hop.
"""

from functools import lru_cache

import redis
from rq import Queue

from offerleaks.core.config import get_settings


@lru_cache
def get_sync_redis() -> redis.Redis:
    settings = get_settings()
    return redis.Redis.from_url(settings.redis_url)


@lru_cache
def get_analysis_queue() -> Queue:
    settings = get_settings()
    return Queue(settings.analysis_queue_name, connection=get_sync_redis())


@lru_cache
def get_company_queue() -> Queue:
    """M7: a second, separate queue for company-profile refresh jobs.
    Deliberately not the same queue as `get_analysis_queue()` -- a slow
    or backed-up external WHOIS/reachability lookup must never delay an
    analysis job sitting behind it (or vice versa); they're independent
    concerns with independent cost/latency profiles.
    """
    settings = get_settings()
    return Queue(settings.company_refresh_queue_name, connection=get_sync_redis())
