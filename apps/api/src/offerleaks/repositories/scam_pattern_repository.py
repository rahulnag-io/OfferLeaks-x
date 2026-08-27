"""Data access for `ScamPattern`.

Read-only in v1: patterns are seeded/edited via migration (see
`migrations/versions/`), matching M6's scope ("Scam Pattern Library" as a
detection input, not an admin-authoring UI -- that's V8 Admin &
Moderation territory). Routers/services never query `ScamPattern`
directly (architecture.md §0.3).
"""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.scam_pattern import ScamPattern


class ScamPatternRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def list_active(self) -> list[ScamPattern]:
        result = await self._db.execute(
            select(ScamPattern).where(ScamPattern.is_active.is_(True))
        )
        return list(result.scalars().all())
