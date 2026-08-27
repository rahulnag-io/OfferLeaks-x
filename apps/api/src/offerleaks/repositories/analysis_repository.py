"""Data access for `Analysis`/`Verdict`.

Routers and services never issue SQLAlchemy queries directly against
these tables -- they go through this repository (architecture.md §0.3).
"""

import uuid
from datetime import datetime

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.analysis import Analysis, AnalysisStatus, Verdict


class AnalysisRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        file_storage_key: str,
        file_name: str,
        file_mime_type: str,
        file_size_bytes: int,
        prompt_version: str,
        source_analysis_id: uuid.UUID | None = None,
    ) -> Analysis:
        analysis = Analysis(
            user_id=user_id,
            file_storage_key=file_storage_key,
            file_name=file_name,
            file_mime_type=file_mime_type,
            file_size_bytes=file_size_bytes,
            prompt_version=prompt_version,
            source_analysis_id=source_analysis_id,
            status=AnalysisStatus.PENDING,
        )
        self._db.add(analysis)
        await self._db.flush()
        return analysis

    async def get_by_id(self, analysis_id: uuid.UUID) -> Analysis | None:
        return await self._db.get(Analysis, analysis_id)

    async def count_since(self, user_id: uuid.UUID, *, since: datetime) -> int:
        """Count of `user_id`'s analyses created at/after `since`. Used
        by M6's `EntitlementService` for the free-plan monthly-analysis
        cap -- a plain count, not a separate usage-tracking table,
        because `analyses` already *is* the authoritative record of
        every analysis a user has created; a redundant counter would
        just be another thing that could drift from it.
        """
        result = await self._db.execute(
            select(func.count())
            .select_from(Analysis)
            .where(Analysis.user_id == user_id, Analysis.created_at >= since)
        )
        return result.scalar_one()

    async def try_start_processing(self, analysis_id: uuid.UUID) -> Analysis | None:
        """Atomically moves `analysis_id` from PENDING to PROCESSING,
        stamping `processing_started_at`. Returns the updated row if this
        call made the transition, `None` if it was no longer PENDING --
        either a duplicate/redelivered RQ job for an analysis another
        worker already started, or the reconciliation sweep already timed
        it out from under this call (see `offerleaks/reconciliation.py`).

        Single conditional `UPDATE ... WHERE status = 'pending' RETURNING
        ...` -- same atomic-claim pattern as `try_consume`/
        `try_claim_free_recheck`. Callers MUST NOT proceed with OCR/AI
        work when this returns `None`.
        """
        stmt = (
            update(Analysis)
            .where(Analysis.id == analysis_id, Analysis.status == AnalysisStatus.PENDING)
            .values(status=AnalysisStatus.PROCESSING, processing_started_at=func.now())
            .returning(Analysis)
        )
        result = await self._db.execute(stmt)
        analysis = result.scalar_one_or_none()
        await self._db.flush()
        return analysis

    async def try_transition(
        self,
        analysis_id: uuid.UUID,
        *,
        from_status: AnalysisStatus,
        to_status: AnalysisStatus,
        error_message: str | None = None,
        failure_reason: str | None = None,
    ) -> Analysis | None:
        """Atomically moves `analysis_id` from `from_status` to
        `to_status`, iff it is still in `from_status` at the moment the
        `UPDATE` runs. Returns the updated row if this call made the
        transition, `None` if it lost the race -- another actor (a
        concurrent worker job, or the reconciliation sweep) already moved
        it out of `from_status`.

        This is the one place any COMPLETE/FAILED/NEEDS_MANUAL_REVIEW
        write happens for an analysis coming out of PROCESSING (worker.py)
        or PENDING/PROCESSING (the reconciliation sweep's timeout claim) --
        a single conditional `UPDATE ... WHERE status = :from_status
        RETURNING ...`, the same atomic-claim pattern as
        `try_consume`/`try_claim_free_recheck`/`try_start_processing`.

        Callers MUST NOT persist a `Verdict`, refund credits, or otherwise
        act on the analysis when this returns `None` -- it is no longer
        theirs to finish.
        """
        stmt = (
            update(Analysis)
            .where(Analysis.id == analysis_id, Analysis.status == from_status)
            .values(status=to_status, error_message=error_message, failure_reason=failure_reason)
            .returning(Analysis)
        )
        result = await self._db.execute(stmt)
        analysis = result.scalar_one_or_none()
        await self._db.flush()
        return analysis

    async def find_stuck_candidates(
        self, *, pending_cutoff: datetime, processing_cutoff: datetime, limit: int
    ) -> list[Analysis]:
        """Plain (non-atomic) read of analyses that *look* stuck: PENDING
        since before `pending_cutoff`, or PROCESSING since before
        `processing_cutoff`. Ordered oldest-first so the longest-stuck
        analyses are reconciled first if a sweep hits `limit`.

        Not itself safe against concurrent reconciliation passes or a
        worker legitimately finishing in the meantime -- callers MUST
        re-confirm each candidate via `try_transition` before acting on
        it (see `run_reconciliation_sweep` in `offerleaks/reconciliation.py`),
        which is where the actual atomicity/race-safety lives. This
        method only narrows down what to check.
        """
        stmt = (
            select(Analysis)
            .where(
                or_(
                    and_(
                        Analysis.status == AnalysisStatus.PENDING,
                        Analysis.created_at < pending_cutoff,
                    ),
                    and_(
                        Analysis.status == AnalysisStatus.PROCESSING,
                        Analysis.processing_started_at.is_not(None),
                        Analysis.processing_started_at < processing_cutoff,
                    ),
                )
            )
            .order_by(Analysis.created_at.asc())
            .limit(limit)
        )
        result = await self._db.execute(stmt)
        return list(result.scalars().all())

    async def get_owned_by(self, analysis_id: uuid.UUID, user_id: uuid.UUID) -> Analysis | None:
        result = await self._db.execute(
            select(Analysis).where(Analysis.id == analysis_id, Analysis.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def list_owned_by(
        self,
        user_id: uuid.UUID,
        *,
        limit: int,
        offset: int,
        status_filter: AnalysisStatus | None = None,
    ) -> tuple[list[Analysis], int]:
        """Returns `(page, total_count)` for `user_id`'s analyses, newest
        first (Version 5 dashboard/history). `total_count` reflects the
        filter, not the whole table, so the frontend can paginate
        correctly against a filtered view.

        Scoped to `user_id` the same way every other analysis query is
        (architecture.md §0.10: identity always derives from the verified
        auth context, never a client-supplied id) -- there is no variant
        of this method that takes an arbitrary user id.
        """
        conditions = [Analysis.user_id == user_id]
        if status_filter is not None:
            conditions.append(Analysis.status == status_filter)

        count_result = await self._db.execute(
            select(func.count()).select_from(Analysis).where(*conditions)
        )
        total = count_result.scalar_one()

        page_result = await self._db.execute(
            select(Analysis)
            .where(*conditions)
            .order_by(Analysis.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(page_result.scalars().all()), total

    async def try_claim_free_recheck(self, analysis_id: uuid.UUID) -> bool:
        """Atomically claims `analysis_id`'s one allowed free re-check.

        Returns `True` if this call is the one that claimed it (proceed
        free), `False` if it was already claimed (charge instead). A
        single conditional `UPDATE ... WHERE free_recheck_claimed = false
        RETURNING ...` -- Postgres takes the row lock as part of the
        `UPDATE`, so two concurrent re-check requests for the same source
        analysis serialize on it the same way `CreditRepository.try_consume`
        serializes concurrent charges on a balance row. Only ever call this
        once the caller has already decided the re-check would otherwise
        qualify as free (e.g. the prompt version hasn't changed) --
        claiming it and then charging anyway would burn the free slot for
        nothing.
        """
        stmt = (
            update(Analysis)
            .where(Analysis.id == analysis_id, Analysis.free_recheck_claimed.is_(False))
            .values(free_recheck_claimed=True)
            .returning(Analysis.id)
        )
        result = await self._db.execute(stmt)
        claimed = result.scalar_one_or_none() is not None
        await self._db.flush()
        return claimed

    async def release_free_recheck(self, analysis_id: uuid.UUID) -> None:
        """Gives back a claimed free re-check that never actually ran --
        the symmetric counterpart to `CreditService.refund_for_analysis`
        for the free (uncharged) re-check path (see
        `AnalysisService.recheck_analysis`'s enqueue-failure handling): the
        user got nothing for the slot they used, so it shouldn't count
        against them. Unconditional set, not a conditional `UPDATE ...
        WHERE ... = true` -- there's nothing to serialize against here,
        the caller already knows it was this same request that claimed it.
        """
        stmt = (
            update(Analysis)
            .where(Analysis.id == analysis_id)
            .values(free_recheck_claimed=False)
        )
        await self._db.execute(stmt)
        await self._db.flush()

    async def get_verdicts_for(self, analysis_ids: list[uuid.UUID]) -> dict[uuid.UUID, Verdict]:
        """Bulk verdict lookup for a page of analyses, so listing history
        doesn't do one query per row."""
        if not analysis_ids:
            return {}
        result = await self._db.execute(
            select(Verdict).where(Verdict.analysis_id.in_(analysis_ids))
        )
        return {verdict.analysis_id: verdict for verdict in result.scalars().all()}

    async def set_status(
        self, analysis: Analysis, status: AnalysisStatus, *, error_message: str | None = None
    ) -> None:
        analysis.status = status
        analysis.error_message = error_message
        await self._db.flush()

    async def get_verdict(self, analysis_id: uuid.UUID) -> Verdict | None:
        result = await self._db.execute(select(Verdict).where(Verdict.analysis_id == analysis_id))
        return result.scalar_one_or_none()

    async def create_verdict(
        self,
        *,
        analysis_id: uuid.UUID,
        risk_score: int,
        red_flags: list[dict[str, str]],
        reasoning: str,
        confidence: float,
        matched_patterns: list[dict[str, str]] | None = None,
        recommended_actions: list[str] | None = None,
        evidence_coverage: float = 0.0,
    ) -> Verdict:
        verdict = Verdict(
            analysis_id=analysis_id,
            risk_score=risk_score,
            red_flags=red_flags,
            reasoning=reasoning,
            confidence=confidence,
            matched_patterns=matched_patterns or [],
            recommended_actions=recommended_actions or [],
            evidence_coverage=evidence_coverage,
        )
        self._db.add(verdict)
        await self._db.flush()
        return verdict
