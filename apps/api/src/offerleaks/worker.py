"""Background job: OCR -> AI verdict for one `Analysis` (architecture.md
§0.7/§0.8). Runs in a separate RQ worker process, never inline in the
request/response cycle -- large or multi-page documents can take well
beyond a reasonable HTTP timeout.

Entrypoint for running a worker process:

    uv run python -m offerleaks.worker
"""

import asyncio
import logging
import sys
import uuid
from collections.abc import Awaitable, Callable, Sequence

from rq import Queue
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.core.config import get_settings
from offerleaks.core.db import async_session_factory
from offerleaks.core.queue import get_analysis_queue, get_company_queue, get_sync_redis
from offerleaks.core.redis import redis_client
from offerleaks.models.analysis import Analysis, AnalysisFailureReason, AnalysisStatus
from offerleaks.providers.ai import AIPermanentError, AITransientError
from offerleaks.providers.factory import (
    get_ai_provider,
    get_domain_age_provider,
    get_ocr_provider,
    get_storage_provider,
    get_website_reachability_provider,
)
from offerleaks.providers.ocr import OCRPermanentError, OCRTransientError
from offerleaks.providers.storage import StorageError, StorageTransientError
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.services.company_extraction import extract_company_signals
from offerleaks.services.company_profile_service import CompanyProfileService
from offerleaks.services.credit_service import CreditService
from offerleaks.services.rules_engine import RulesEngine

logger = logging.getLogger(__name__)

# Generic error messages stored on the analysis row -- never the raw
# provider exception string (§0.11: no sensitive payload contents, and
# no internal error detail leaked to the end user).
_STORAGE_FAILURE_MESSAGE = "We couldn't retrieve your uploaded file. Please try uploading again."
_OCR_FAILURE_MESSAGE = "We couldn't read this document. Please try a clearer scan or photo."
_AI_MANUAL_REVIEW_MESSAGE = (
    "Automatic analysis couldn't be completed for this document, so it's been queued for "
    "manual review. Your credit for this analysis has been automatically refunded."
)
_UNEXPECTED_FAILURE_MESSAGE = "Something went wrong while analyzing this document."


async def _retry[T](
    fn: Callable[[], Awaitable[T]],
    *,
    retryable: type[Exception] | tuple[type[Exception], ...],
    max_attempts: int,
    backoff_seconds: float = 2.0,
) -> T:
    """Retries `fn` up to `max_attempts` times on `retryable` exceptions,
    with linear backoff. Any other exception propagates immediately."""
    last_exc: Exception | None = None
    for attempt in range(max_attempts):
        try:
            return await fn()
        except retryable as exc:
            last_exc = exc
            if attempt + 1 < max_attempts:
                logger.warning(
                    "provider call failed (attempt %d/%d), retrying: %s",
                    attempt + 1,
                    max_attempts,
                    type(exc).__name__,
                )
                await asyncio.sleep(backoff_seconds * (attempt + 1))
    assert last_exc is not None  # max_attempts >= 1 guarantees at least one iteration
    raise last_exc


def _truncate_for_ai(text: str, max_characters: int) -> str:
    if len(text) <= max_characters:
        return text
    logger.info(
        "truncating OCR text from %d to %d characters before the AI call",
        len(text),
        max_characters,
    )
    return text[:max_characters]


async def _process_analysis(analysis_id: uuid.UUID) -> None:
    settings = get_settings()

    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        analysis = await repo.get_by_id(analysis_id)
        if analysis is None:
            logger.error("analysis %s not found; nothing to process", analysis_id)
            return

        # Guards against a redelivered/duplicate RQ job re-running an
        # analysis that already reached a terminal state. Previously this
        # was only accidentally safe (a second `create_verdict` call would
        # hit the unique constraint on `Verdict.analysis_id` and raise,
        # which `process_analysis` would catch and mark FAILED) -- with
        # Version 4's credit refunds, that accidental path would have
        # incorrectly refunded credits for a successful analysis. Making
        # the no-op explicit here closes that off directly instead of
        # relying on happening to fail in a safe-looking way.
        if analysis.status in (
            AnalysisStatus.COMPLETE,
            AnalysisStatus.FAILED,
            AnalysisStatus.NEEDS_MANUAL_REVIEW,
        ):
            logger.warning(
                "analysis %s already in terminal state %s; skipping duplicate job",
                analysis_id,
                analysis.status,
            )
            return

        started = await repo.try_start_processing(analysis_id)
        if started is None:
            # Lost the race for this analysis: either a duplicate/
            # redelivered job for one another worker already started
            # (the terminal-state check above only catches COMPLETE/
            # FAILED/NEEDS_MANUAL_REVIEW, not "another worker already
            # flipped this to PROCESSING a moment ago"), or the
            # reconciliation sweep already timed it out from PENDING
            # (offerleaks/reconciliation.py) between the read above and
            # this call. Either way, this job must not proceed.
            logger.warning(
                "analysis %s no longer pending; skipping duplicate/reconciled job", analysis_id
            )
            return
        analysis = started
        await db.commit()

        storage = get_storage_provider()
        try:
            file_bytes = await _retry(
                lambda: storage.download(key=analysis.file_storage_key),
                retryable=StorageTransientError,
                max_attempts=2,
            )
        except (StorageError, StorageTransientError) as exc:
            logger.error("could not download original file for analysis %s: %s", analysis_id, exc)
            await _finish_processing(
                db,
                repo,
                analysis_id,
                to_status=AnalysisStatus.FAILED,
                error_message=_STORAGE_FAILURE_MESSAGE,
                failure_reason=AnalysisFailureReason.STORAGE_UNAVAILABLE,
                refund_reason="storage failure",
            )
            return

        # --- OCR ---
        ocr = get_ocr_provider()
        try:
            extracted = await _retry(
                lambda: ocr.extract(file_bytes=file_bytes, mime_type=analysis.file_mime_type),
                retryable=OCRTransientError,
                max_attempts=2,
            )
        except (OCRTransientError, OCRPermanentError) as exc:
            logger.error("OCR failed permanently for analysis %s: %s", analysis_id, exc)
            await _finish_processing(
                db,
                repo,
                analysis_id,
                to_status=AnalysisStatus.FAILED,
                error_message=_OCR_FAILURE_MESSAGE,
                failure_reason=AnalysisFailureReason.OCR_FAILED,
                refund_reason="OCR failure",
            )
            return

        document_text = _truncate_for_ai(extracted.text, settings.ai_max_input_characters)

        # --- M6: rules engine (deterministic, alongside the AI call) ---
        # Pure text matching against the DB-backed scam pattern library --
        # no external call, so no retry/transient-error handling needed
        # here the way the AI/OCR calls above have. Runs against the full
        # (untruncated) OCR text, not `document_text` -- the AI's input
        # is capped for cost (§0.6), but pattern matching is a local
        # string scan with no such cost concern.
        rules_result = await RulesEngine(db).match(text=extracted.text)

        # --- M7: company signal & reputation (deterministic, best-effort) ---
        # Runs against the full OCR text, alongside the rules engine, for
        # the same reason: a local/cheap step, no reason to gate it on
        # the AI call. Failure here must never fail the analysis itself
        # -- company-signal resolution is a value-add, not a pipeline
        # dependency (M7 §14).
        try:
            await _attach_company_profile(db, analysis, extracted.text)
        except Exception:
            logger.exception(
                "company profile resolution failed for analysis %s (non-fatal)", analysis_id
            )

        # --- AI verdict ---
        # §0.6 fallback strategy: retry once, then degrade to
        # "manual review pending" rather than fabricate a verdict. This
        # applies to both transient and permanent AI failures alike --
        # the architecture doc doesn't distinguish for this step the way
        # it does for OCR.
        ai = get_ai_provider()
        try:
            verdict = await _retry(
                lambda: ai.analyze_offer_letter(
                    text=document_text, prompt_version=analysis.prompt_version
                ),
                retryable=(AITransientError, AIPermanentError),
                max_attempts=2,
            )
        except (AITransientError, AIPermanentError) as exc:
            logger.error(
                "AI analysis failed after retry for analysis %s, routing to manual review: %s",
                analysis_id,
                exc,
            )
            # Refunded here too: unlike a plain retryable transient error,
            # an AI failure that survives the retry in `_retry(...)` above
            # means no verdict was produced at all -- the user is being
            # asked to wait on a human reviewer instead of getting what
            # they paid for automatically, so the credit is given back.
            # See `_refund_credits`'s docstring for the full policy.
            await _finish_processing(
                db,
                repo,
                analysis_id,
                to_status=AnalysisStatus.NEEDS_MANUAL_REVIEW,
                error_message=_AI_MANUAL_REVIEW_MESSAGE,
                failure_reason=AnalysisFailureReason.AI_FAILED,
                refund_reason="AI provider failure (manual review)",
            )
            return

        # Claimed *before* the verdict is persisted, not after: if this
        # returns `None` -- the reconciliation sweep already timed this
        # analysis out from PROCESSING to FAILED while the AI call above
        # was in flight, refunding the credit for it -- the verdict must
        # never be written at all. Writing it after the fact would leave a
        # `Verdict` row hanging off an analysis whose credit was already
        # refunded, delivering the paid-for result for free and silently
        # contradicting the FAILED status the user already saw.
        claimed = await repo.try_transition(
            analysis_id, from_status=AnalysisStatus.PROCESSING, to_status=AnalysisStatus.COMPLETE
        )
        if claimed is None:
            logger.warning(
                "analysis %s no longer processing; discarding verdict (likely reconciled "
                "as stuck while the AI call was in flight)",
                analysis_id,
            )
            await db.rollback()
            return

        # Merge the AI's own red flags with the rules engine's
        # deterministic pattern matches -- two independent signals, both
        # surfaced, neither silently dropped. `evidence_coverage` and
        # `recommended_actions` are computed over the *merged* set so a
        # rules-engine match (which always carries a real evidence quote,
        # see `RulesEngine.match`) correctly raises the coverage score
        # rather than only reflecting how many of the AI's own flags
        # happened to include one.
        merged_red_flags = list(verdict.red_flags) + rules_result.pattern_red_flags
        recommended_actions = RulesEngine.recommended_actions_for(
            risk_score=verdict.risk_score, red_flags=merged_red_flags
        )

        await repo.create_verdict(
            analysis_id=analysis.id,
            risk_score=verdict.risk_score,
            red_flags=[flag.model_dump() for flag in merged_red_flags],
            reasoning=verdict.reasoning,
            confidence=verdict.confidence,
            matched_patterns=[p.model_dump() for p in rules_result.matched_patterns],
            recommended_actions=recommended_actions,
            evidence_coverage=RulesEngine.evidence_coverage(merged_red_flags),
        )
        await db.commit()


async def _finish_processing(
    db: AsyncSession,
    repo: AnalysisRepository,
    analysis_id: uuid.UUID,
    *,
    to_status: AnalysisStatus,
    error_message: str,
    failure_reason: AnalysisFailureReason,
    refund_reason: str,
) -> None:
    """Atomically moves `analysis_id` out of PROCESSING into `to_status`
    (FAILED or NEEDS_MANUAL_REVIEW), refunds the credit, and commits both
    together -- the shared tail end of every failure/manual-review path in
    `_process_analysis`.

    If the atomic claim (`AnalysisRepository.try_transition`) loses the
    race -- the reconciliation sweep already timed this analysis out from
    under this worker (`offerleaks/reconciliation.py`), refunding it in
    the process -- this is a no-op: no double status write, and no
    redundant refund attempt (the sweep already made one, and
    `refund_for_analysis` is idempotent regardless).
    """
    claimed = await repo.try_transition(
        analysis_id,
        from_status=AnalysisStatus.PROCESSING,
        to_status=to_status,
        error_message=error_message,
        failure_reason=failure_reason,
    )
    if claimed is None:
        logger.warning(
            "analysis %s no longer processing; skipping duplicate/reconciled terminal write",
            analysis_id,
        )
        await db.rollback()
        return

    await _refund_credits(db, claimed.id, claimed.user_id, reason=refund_reason)
    await db.commit()


async def _refund_credits(
    db: AsyncSession,
    analysis_id: uuid.UUID,
    user_id: uuid.UUID,
    *,
    reason: str,
) -> None:
    """Restores the credit spent on an analysis that did not produce an
    automatic verdict -- whether because processing failed outright
    (`FAILED`: storage/OCR/unexpected error/stuck-analysis timeout) or
    because it degraded to `NEEDS_MANUAL_REVIEW` (the AI provider call
    failed even after retry). In both cases the user did not receive the
    automated result their credit paid for, so the credit is given back
    rather than kept for work that was queued to a human instead (roadmap
    §12: never silently keep a user's credits for an analysis that never
    produced a verdict).

    Idempotent (via `CreditService.refund_for_analysis`), so a worker
    retry, a redelivered job, or the reconciliation sweep
    (`offerleaks/reconciliation.py`) reaching this a second time for the
    same analysis is a safe no-op -- it will not refund twice, which is
    the one invariant this feature can never violate.

    Must be called, and awaited, before the caller's `await db.commit()`
    for the same status-update transaction: the status write and the
    refund are meant to land together or not at all.
    """
    refunded = await CreditService(db).refund_for_analysis(
        user_id=user_id, analysis_id=analysis_id
    )
    if refunded:
        logger.info("refunded credits for analysis %s (%s)", analysis_id, reason)


def _get_company_profile_service(db: AsyncSession) -> CompanyProfileService:
    return CompanyProfileService(
        db,
        redis_client,
        get_domain_age_provider(),
        get_website_reachability_provider(),
    )


async def _attach_company_profile(db: AsyncSession, analysis: Analysis, document_text: str) -> None:
    """M7: resolves (or creates) the shared `Company` this analysis's
    document is attributed to, from deterministic extraction over the
    OCR text -- and, if resolvable, links it onto the analysis and
    opportunistically kicks off a background refresh if the cached
    profile is missing or stale. A `None` resolution (no sender domain
    or company name found at all) is left as `analysis.company_id =
    NULL`, the honest "nothing to resolve" state -- never a fabricated
    company record.
    """
    extracted = extract_company_signals(document_text)
    service = _get_company_profile_service(db)
    company = await service.resolve_for_analysis(
        sender_domain=extracted.sender_domain, company_name=extracted.company_name
    )
    if company is not None:
        analysis.company_id = company.id
        await db.flush()


async def refresh_company_profile(company_id: str) -> None:
    """RQ entrypoint (M7): recomputes the domain-age/website-reachability/
    verification-status signal set for one company and persists it,
    Postgres-first (Redis is repopulated from the result). Enqueued only
    by `CompanyProfileService.ensure_fresh`, which already holds a
    short-lived Redis lock for this company -- a redelivered/duplicate
    job for the same company is still safe here regardless, since
    `CompanyRepository.upsert_signal` is a plain last-write-wins update,
    not an append.
    """
    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        company = await repo.get_by_id(uuid.UUID(company_id))
        if company is None:
            logger.warning("company %s not found; nothing to refresh", company_id)
            return

        service = _get_company_profile_service(db)
        try:
            await service.perform_refresh(company)
        except Exception:
            logger.exception("company profile refresh failed for company %s", company_id)
            await db.rollback()
            return
        await db.commit()


def process_company_refresh(company_id: str) -> None:
    """Sync RQ entrypoint bridging into the async implementation, same
    pattern as `process_analysis` below."""
    try:
        asyncio.run(refresh_company_profile(company_id))
    except Exception:
        logger.exception("unexpected error refreshing company %s", company_id)
        raise


async def _mark_failed_generic(analysis_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        await _finish_processing(
            db,
            repo,
            analysis_id,
            to_status=AnalysisStatus.FAILED,
            error_message=_UNEXPECTED_FAILURE_MESSAGE,
            failure_reason=AnalysisFailureReason.WORKER_CRASH,
            refund_reason="unexpected worker error",
        )


def process_analysis(analysis_id: str) -> None:
    """RQ entrypoint (sync, per RQ's job-function contract). Bridges into
    the async implementation with its own event loop -- this always runs
    in a dedicated worker process, one job at a time, so a fresh loop per
    job is simple and correct rather than a bottleneck.

    Every *known* provider failure path inside `_process_analysis` already
    records a typed status (FAILED/NEEDS_MANUAL_REVIEW) and returns
    normally. Anything that reaches here is an unexpected bug, not a
    handled provider error -- it's recorded generically (so the row never
    sits in PROCESSING forever) and then re-raised so RQ's own failure
    tracking sees it too (§0.11: no error is silently swallowed).
    """
    try:
        asyncio.run(_process_analysis(uuid.UUID(analysis_id)))
    except Exception:
        logger.exception("unexpected error processing analysis %s", analysis_id)
        asyncio.run(_mark_failed_generic(uuid.UUID(analysis_id)))
        raise


_QUEUE_FACTORIES: dict[str, Callable[[], Queue]] = {
    "analysis": get_analysis_queue,
    "company_refresh": get_company_queue,
}


def _resolve_queues(queue_names: Sequence[str] | None) -> list[Queue]:
    """Maps logical queue names (`"analysis"`, `"company_refresh"`) to
    their actual RQ `Queue` objects. `None` (the default) means "listen
    on both" -- the original, backward-compatible behavior for anyone
    running the worker with no arguments. A restricted subset is what
    lets a *second* worker process listen only to `company_refresh` (see
    `docker-compose.yml`'s `company_worker` service), so a slow/backed-up
    external domain-age or reachability lookup can never delay analysis
    processing behind it on a shared process -- something a single
    worker consuming both queues cannot actually guarantee, even though
    the queues themselves are already logically separate.
    """
    if queue_names is None:
        return [get_analysis_queue(), get_company_queue()]
    return [_QUEUE_FACTORIES[name]() for name in queue_names]


def _parse_queue_names_from_argv(argv: Sequence[str]) -> Sequence[str] | None:
    """Parses `--queues=analysis,company_refresh` (comma-separated logical
    names) from CLI args. Returns `None` (both queues) if not supplied."""
    for arg in argv:
        if arg.startswith("--queues="):
            names = [n.strip() for n in arg.split("=", 1)[1].split(",") if n.strip()]
            unknown = set(names) - set(_QUEUE_FACTORIES)
            if unknown:
                raise ValueError(
                    f"unknown queue name(s) {sorted(unknown)}; "
                    f"valid names are {sorted(_QUEUE_FACTORIES)}"
                )
            return names or None
    return None


def _run_worker(queue_names: Sequence[str] | None = None) -> None:
    """RQ's fork-based job supervision (`Worker`, and -- despite the
    name -- `SpawnWorker` too) relies on POSIX-only APIs in the *parent*
    process (`os.wait4` to reap the child), not just `os.fork()` to
    create it. Neither works on native Windows.

    `SimpleWorker` runs jobs in this same process instead of a forked
    child, so it never touches that code path -- but it also loses
    process isolation and RQ's timeout-kill enforcement, which is fine
    for local iteration but wrong for anything that isn't. It's
    auto-selected only on Windows for that reason; production always
    runs in a Linux container (this project's Docker setup, per
    architecture.md §0.10), where the fully-isolated `Worker` is used.
    """
    connection = get_sync_redis()
    queues = _resolve_queues(queue_names)

    if sys.platform == "win32":
        from rq import SimpleWorker

        logger.warning(
            "Running RQ's SimpleWorker (in-process, no job isolation or timeout "
            "enforcement) because RQ's fork-based Worker cannot run on native "
            "Windows. This is fine for local development; run the worker inside "
            "Docker (see docker-compose.yml) for anything closer to production."
        )
        worker = SimpleWorker(queues, connection=connection)
    else:
        from rq import Worker

        worker = Worker(queues, connection=connection)

    worker.work()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    _run_worker(_parse_queue_names_from_argv(sys.argv[1:]))
