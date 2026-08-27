"""Backend-owned recovery for analyses stuck in PENDING or PROCESSING --
e.g. no worker ever picked the job up, or a worker process crashed, was
killed, or was force-timed-out by RQ mid-job without running its own
cleanup path (see `worker.py`'s `process_analysis`/`_mark_failed_generic`
docstrings for exactly which failures those *do* already cover).

This runs independently of the frontend and of any particular worker
process -- the person can close their browser, lose connectivity, or
never come back, and a stuck analysis still gets resolved and its credit
refunded. The backend is the only source of truth here; there is no
client-side timer anywhere in this feature.

Entrypoint for running this as its own long-lived process (mirrors
`worker.py`'s `python -m offerleaks.worker`):

    uv run python -m offerleaks.reconciliation           # loop forever
    uv run python -m offerleaks.reconciliation --once     # one sweep, then exit

See `docker-compose.yml`'s `reconciler` service for how this runs
alongside the worker in Docker.
"""

import argparse
import asyncio
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.core.config import get_settings
from offerleaks.core.db import async_session_factory
from offerleaks.models.analysis import Analysis, AnalysisFailureReason, AnalysisStatus
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.services.credit_service import CreditService

logger = logging.getLogger(__name__)

# User-facing, deliberately generic -- never the internal
# `AnalysisFailureReason` (architecture.md §0.11: no internal error
# detail leaked to the end user). Whether a credit was actually refunded
# is reported precisely via `AnalysisResponse.credit_refunded`, not
# guessed at in this string, since a PENDING-timeout analysis that was
# never charged (enqueue failed before charging -- can't currently
# happen, but nothing here assumes it can't) has nothing to refund.
_STUCK_ANALYSIS_MESSAGE = (
    "This took longer than expected and was automatically stopped. If a credit was "
    "charged for it, that credit has been refunded. Please try again."
)


@dataclass(slots=True)
class ReconciliationResult:
    """Summary of one sweep -- returned for logging, and asserted on
    directly in tests rather than re-deriving it from DB state."""

    candidates_seen: int = 0
    analyses_failed: int = 0
    credits_refunded: int = 0
    # Candidates that were no longer PENDING/PROCESSING by the time this
    # sweep tried to claim them -- a worker finished first, or another
    # concurrent reconciliation sweep already claimed it. Not an error.
    lost_races: int = 0


async def run_reconciliation_sweep() -> ReconciliationResult:
    """One pass: find analyses stuck past their configured timeout,
    atomically flip each to FAILED, and refund its credit if it had one.

    Safe to run concurrently with itself (two reconciliation processes at
    once, or overlapping sweeps if one runs long) and safe to run
    repeatedly over the same analysis. Every state change here goes
    through `AnalysisRepository.try_transition`'s conditional `UPDATE ...
    WHERE status = :from_status`, so only one caller can ever win the
    claim on a given row, and `CreditService.refund_for_analysis`'s
    ledger-uniqueness guarantee, so even a hypothetical double-claim could
    never double-refund. Neither of those is new machinery built for this
    sweep -- they're the exact same atomic-claim / idempotent-ledger
    primitives `try_consume`/`try_claim_free_recheck`/`try_start_processing`
    already use elsewhere in this codebase.
    """
    settings = get_settings()
    now = datetime.now(UTC)
    pending_cutoff = now - timedelta(seconds=settings.pending_analysis_timeout_seconds)
    processing_cutoff = now - timedelta(seconds=settings.processing_analysis_timeout_seconds)

    result = ReconciliationResult()

    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        candidates = await repo.find_stuck_candidates(
            pending_cutoff=pending_cutoff,
            processing_cutoff=processing_cutoff,
            limit=settings.reconciliation_batch_size,
        )
        result.candidates_seen = len(candidates)

        for candidate in candidates:
            try:
                await _reconcile_one(db, repo, candidate, result)
            except Exception:
                # One bad row must not abort the rest of the sweep. Roll
                # back so this row's (uncommitted) claim doesn't leak into
                # the next iteration's transaction, and try again on the
                # next sweep -- nothing partially committed here, since
                # the claim and the refund below land together or not at
                # all (see `_reconcile_one`).
                logger.exception(
                    "reconciliation failed for analysis %s; will retry next sweep", candidate.id
                )
                await db.rollback()

    if result.candidates_seen:
        logger.info(
            "reconciliation sweep: %d candidate(s), %d marked failed, %d credit(s) refunded, "
            "%d already resolved elsewhere",
            result.candidates_seen,
            result.analyses_failed,
            result.credits_refunded,
            result.lost_races,
        )
    return result


async def _reconcile_one(
    db: AsyncSession,
    repo: AnalysisRepository,
    candidate: Analysis,
    result: ReconciliationResult,
) -> None:
    failure_reason = (
        AnalysisFailureReason.PENDING_TIMEOUT
        if candidate.status == AnalysisStatus.PENDING
        else AnalysisFailureReason.PROCESSING_TIMEOUT
    )

    claimed = await repo.try_transition(
        candidate.id,
        from_status=candidate.status,
        to_status=AnalysisStatus.FAILED,
        error_message=_STUCK_ANALYSIS_MESSAGE,
        failure_reason=failure_reason,
    )
    if claimed is None:
        # A worker finished it, or another reconciliation sweep already
        # claimed it, between the candidate SELECT and this UPDATE.
        result.lost_races += 1
        return

    result.analyses_failed += 1
    refunded = await CreditService(db).refund_for_analysis(
        user_id=claimed.user_id, analysis_id=claimed.id
    )
    if refunded:
        result.credits_refunded += 1
    await db.commit()

    logger.info(
        "reconciliation: analysis %s marked FAILED (%s), credit refunded: %s",
        claimed.id,
        failure_reason.value,
        refunded,
    )


async def _run_loop() -> None:
    settings = get_settings()
    logger.info(
        "reconciliation loop starting (interval=%ds, pending_timeout=%ds, "
        "processing_timeout=%ds)",
        settings.reconciliation_interval_seconds,
        settings.pending_analysis_timeout_seconds,
        settings.processing_analysis_timeout_seconds,
    )
    while True:
        try:
            await run_reconciliation_sweep()
        except Exception:
            # A sweep-level failure (e.g. the DB is briefly unreachable)
            # must not kill the whole process -- there's no supervisor
            # restarting this loop the way RQ's Worker restarts job
            # handling, so the loop has to be its own safety net.
            logger.exception("reconciliation sweep failed; will retry next interval")
        await asyncio.sleep(settings.reconciliation_interval_seconds)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--once",
        action="store_true",
        help=(
            "Run a single sweep and exit, instead of looping forever. Use this if an "
            "external scheduler (host cron, a Kubernetes CronJob, etc.) is what triggers "
            "each sweep, rather than this process staying up and sleeping between them."
        ),
    )
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO)
    if args.once:
        result = asyncio.run(run_reconciliation_sweep())
        logger.info(
            "single sweep complete: %d candidate(s), %d marked failed, %d credit(s) refunded",
            result.candidates_seen,
            result.analyses_failed,
            result.credits_refunded,
        )
    else:
        asyncio.run(_run_loop())


if __name__ == "__main__":
    main()
