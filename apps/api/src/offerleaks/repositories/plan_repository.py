"""Data access for `Plan`/`PlanEntitlement`. Read-mostly: plans are seeded
by migration and edited rarely, so there's no client-facing write path in
v1 (mirrors `ScamPatternRepository`)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.plan import FREE_PLAN_KEY, Plan, PlanEntitlement


class PlanRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_key(self, key: str) -> Plan | None:
        result = await self._db.execute(
            select(Plan).where(Plan.key == key, Plan.is_active.is_(True))
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, plan_id: uuid.UUID) -> Plan | None:
        result = await self._db.execute(select(Plan).where(Plan.id == plan_id))
        return result.scalar_one_or_none()

    async def list_active(self) -> list[Plan]:
        result = await self._db.execute(
            select(Plan).where(Plan.is_active.is_(True)).order_by(Plan.price_amount_minor.asc())
        )
        return list(result.scalars().all())

    async def get_free_plan(self) -> Plan:
        plan = await self.get_by_key(FREE_PLAN_KEY)
        if plan is None:
            # Seeded by migration; missing means the DB wasn't migrated
            # correctly, which is a deploy-time error, not a request-time
            # one worth a soft fallback for.
            raise RuntimeError(f"free plan (key={FREE_PLAN_KEY!r}) is missing; check migrations")
        return plan

    async def get_entitlements(self, plan_id: uuid.UUID) -> dict[str, str]:
        result = await self._db.execute(
            select(PlanEntitlement.key, PlanEntitlement.value).where(
                PlanEntitlement.plan_id == plan_id
            )
        )
        return {row.key: row.value for row in result}
