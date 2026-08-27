"""Health check endpoints.

Two tiers, deliberately kept separate:

- `GET /health` -- pure liveness. Answers instantly, no I/O. What a load
  balancer or uptime check should hit.
- `GET /health/dependencies` -- readiness. Actually pings Postgres and
  Redis. Slower and allowed to fail; this is what Version 1's "DB
  provisioned" requirement is verified against, and what the web app's
  homepage calls to render connection status.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.core.config import Settings, get_settings
from offerleaks.core.db import get_db_session
from offerleaks.core.redis import get_redis
from offerleaks.providers.factory import get_malware_scan_provider
from offerleaks.providers.malware_scan import MalwareScanProvider

router = APIRouter(tags=["health"])


class HealthStatus(BaseModel):
    status: Literal["ok"]
    service: str
    version: str


class DependencyHealth(BaseModel):
    database: Literal["ok", "error"]
    redis: Literal["ok", "error"]
    malware_scanner: Literal["ok", "error"]


@router.get("/health", response_model=HealthStatus)
async def health(settings: Settings = Depends(get_settings)) -> HealthStatus:
    return HealthStatus(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
    )


@router.get("/health/dependencies", response_model=DependencyHealth)
async def dependency_health(
    db: AsyncSession = Depends(get_db_session),
    redis: Redis = Depends(get_redis),
    malware_scanner: MalwareScanProvider = Depends(get_malware_scan_provider),
) -> DependencyHealth:
    db_status: Literal["ok", "error"] = "ok"
    redis_status: Literal["ok", "error"] = "ok"
    scanner_status: Literal["ok", "error"] = "ok"

    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        db_status = "error"

    try:
        await redis.ping()
    except Exception:
        redis_status = "error"

    try:
        if not await malware_scanner.ping():
            scanner_status = "error"
    except Exception:
        scanner_status = "error"

    return DependencyHealth(
        database=db_status,
        redis=redis_status,
        malware_scanner=scanner_status,
    )
