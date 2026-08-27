"""Data access for `Report` (M8: Structured Reporting + Reuse Features).

`try_transition_status` follows the same atomic conditional-UPDATE
pattern already used for real invariants elsewhere in the codebase
(`AnalysisRepository.try_claim_free_recheck`, `CreditRepository.
try_consume`): `UPDATE ... WHERE status IN (allowed) RETURNING`, so a
retried/duplicated status-change request can never apply twice or race
another concurrent transition into an inconsistent state -- the second
caller simply sees `None` (no row matched) rather than corrupting
anything.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.report import Report, ReportStatus


class ReportRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(self, report: Report) -> Report:
        self._db.add(report)
        await self._db.flush()
        return report

    async def get_by_id(self, report_id: uuid.UUID) -> Report | None:
        result = await self._db.execute(select(Report).where(Report.id == report_id))
        return result.scalar_one_or_none()

    async def get_owned_by(self, report_id: uuid.UUID, user_id: uuid.UUID) -> Report | None:
        result = await self._db.execute(
            select(Report).where(Report.id == report_id, Report.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_owned_by(
        self, user_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[Report], int]:
        base_stmt = select(Report).where(Report.user_id == user_id)

        count_result = await self._db.execute(
            select(func.count()).select_from(base_stmt.subquery())
        )
        total = count_result.scalar_one()

        result = await self._db.execute(
            base_stmt.order_by(Report.created_at.desc()).limit(limit).offset(offset)
        )
        return list(result.scalars().all()), total

    async def find_recent_for_company(
        self, company_id: uuid.UUID, *, since: datetime
    ) -> list[Report]:
        """Candidate rows for duplicate-window comparison: every report
        (any status, any submitter -- a duplicate complaint from a
        *different* user about the same company within the window is
        still a duplicate for reputation-counting purposes) filed for
        this company since `since`. Deliberately not filtered by
        `is_duplicate` -- a new report is compared against the earliest
        original, not against another already-flagged duplicate, so the
        chain always resolves back to one canonical non-duplicate root
        (`ordered oldest first below`).
        """
        result = await self._db.execute(
            select(Report)
            .where(
                Report.company_id == company_id,
                Report.created_at >= since,
                Report.is_duplicate.is_(False),
            )
            .order_by(Report.created_at.asc())
        )
        return list(result.scalars().all())

    async def try_transition_status(
        self,
        *,
        report_id: uuid.UUID,
        allowed_from: frozenset[ReportStatus],
        to_status: ReportStatus,
    ) -> Report | None:
        """Atomically moves `report_id` to `to_status` iff its current
        status is one of `allowed_from`. Returns the updated row, or
        `None` if no row matched (already transitioned, in a
        non-matching status, or doesn't exist) -- callers must treat
        `None` as "no-op," never as an error to retry, since retrying an
        already-applied transition is exactly the safe-under-retries case
        this exists for.
        """
        stmt = (
            update(Report)
            .where(Report.id == report_id, Report.status.in_(allowed_from))
            .values(status=to_status)
            .returning(Report)
        )
        result = await self._db.execute(stmt)
        await self._db.flush()
        return result.scalar_one_or_none()

    async def count_verified_non_duplicate(self, company_id: uuid.UUID) -> int:
        """Authoritative, always-fresh count backing the internal
        reputation signal (`services/report_service.py::
        _recompute_company_reputation`). A full re-count rather than a
        stored running total -- so calling this twice in a row (a retry,
        a duplicate job execution) always yields the same correct number
        instead of compounding an increment (M8 §13).
        """
        result = await self._db.execute(
            select(func.count())
            .select_from(Report)
            .where(
                Report.company_id == company_id,
                Report.status == ReportStatus.VERIFIED,
                Report.is_duplicate.is_(False),
            )
        )
        return result.scalar_one()
