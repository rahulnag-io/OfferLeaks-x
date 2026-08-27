"""Analysis business logic (Version 3: Upload -> OCR -> AI Verdict).

Orchestrates validation, malware scanning, storage, and job enqueueing.
Routers call this, never the repository or providers directly
(architecture.md §0.3). The actual OCR/AI work happens in
`offerleaks.worker`, never inline here -- this only ever returns a
`PENDING` analysis.
"""

import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.core.config import Settings, get_settings
from offerleaks.core.queue import get_analysis_queue
from offerleaks.models.analysis import Analysis, AnalysisStatus
from offerleaks.models.user import User
from offerleaks.providers.errors import TransientProviderError
from offerleaks.providers.malware_scan import MalwareScanProvider
from offerleaks.providers.storage import StorageProvider
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.services.credit_service import CreditService, InsufficientCreditsError
from offerleaks.services.entitlement_service import (
    EntitlementService,
    MonthlyAnalysisLimitExceededError,
)
from offerleaks.services.file_validation import FileValidationError, validate_upload

logger = logging.getLogger(__name__)


class AnalysisServiceError(Exception):
    """Base class for all analysis-service failures. Routers map this to 4xx."""


class MalwareDetectedError(AnalysisServiceError):
    def __init__(self, threat_name: str | None) -> None:
        super().__init__(threat_name or "malware detected")
        self.threat_name = threat_name


class ScanUnavailableForUploadError(AnalysisServiceError):
    """The malware scanner couldn't be reached. Uploads fail closed --
    "never trusted as safe to render without validation" (§0.11) applies
    to an unscannable file the same as an infected one."""


class AnalysisNotFoundError(AnalysisServiceError):
    pass


class QueueUnavailableError(AnalysisServiceError):
    """The analysis was recorded and charged, but the job could not be
    enqueued. The charge is refunded (idempotently) before this is raised
    -- see `create_analysis` -- so the user is never billed for a job that
    never entered the pipeline."""


class AnalysisNotReadyForRecheckError(AnalysisServiceError):
    """The source analysis hasn't reached a terminal state yet (still
    PENDING/PROCESSING) -- re-checking it now would race the in-flight
    worker job rather than genuinely re-run anything."""


class AnalysisService:
    def __init__(
        self,
        db: AsyncSession,
        storage: StorageProvider,
        malware_scanner: MalwareScanProvider,
    ) -> None:
        self._db = db
        self._analyses = AnalysisRepository(db)
        self._storage = storage
        self._scanner = malware_scanner
        self._credits = CreditService(db)
        self._entitlements = EntitlementService(db)

    async def create_analysis(
        self, *, user: User, file_bytes: bytes, file_name: str
    ) -> Analysis:
        settings: Settings = get_settings()

        # Re-raised as-is; the router maps FileValidationError subclasses
        # to specific 4xx responses.
        mime_type = validate_upload(file_bytes=file_bytes, settings=settings)

        # M6: plan-tier monthly analysis cap, independent of and in
        # addition to the credit check just below (see
        # `EntitlementService` module docstring for why these are two
        # separate gates). Same fast-path caveat as the credit pre-check:
        # not itself atomic, but a plan cap allowing one extra analysis in
        # a rare race is a soft product limit, not a correctness issue.
        await self._entitlements.assert_within_monthly_quota(user.id)

        # Credit eligibility is checked *before* the scan/storage work
        # below -- there's no point spending a malware scan or an S3 write
        # on an upload that's going to be rejected for insufficient
        # credits anyway. This is a fast-path optimization only: it is
        # NOT the authoritative check (a concurrent request could still
        # spend the balance in between), so the real, atomic enforcement
        # still happens further down via `CreditService.charge_for_analysis`
        # in the same transaction as the `Analysis` row's creation.
        current_balance = await self._credits.get_balance(user.id)
        if current_balance < self._credits.cost_per_analysis:
            raise InsufficientCreditsError(
                required=self._credits.cost_per_analysis, available=current_balance
            )

        try:
            scan_result = await self._scanner.scan(file_bytes=file_bytes)
        except TransientProviderError as exc:
            raise ScanUnavailableForUploadError from exc

        if not scan_result.is_clean:
            raise MalwareDetectedError(scan_result.threat_name)

        storage_key = f"analyses/{user.id}/{uuid.uuid4()}/{file_name}"
        await self._storage.upload(key=storage_key, data=file_bytes, content_type=mime_type)

        # Analysis-record creation and the credit charge happen in the same
        # DB transaction: if the charge fails (balance was spent by a
        # concurrent request between the pre-check above and here), the
        # whole transaction rolls back and no Analysis row is left behind.
        analysis = await self._analyses.create(
            user_id=user.id,
            file_storage_key=storage_key,
            file_name=file_name,
            file_mime_type=mime_type,
            file_size_bytes=len(file_bytes),
            prompt_version=settings.ai_prompt_version,
        )
        try:
            await self._credits.charge_for_analysis(user_id=user.id, analysis_id=analysis.id)
        except InsufficientCreditsError:
            # Balance was spent by a concurrent request between the
            # pre-check above and here. Roll back so the Analysis row we
            # just added to the session is discarded, not left pending.
            await self._db.rollback()
            raise
        await self._db.commit()

        # Enqueued by dotted path, not a direct import of `offerleaks.worker`
        # -- that module imports this one to do the actual processing, and
        # importing it back here would be a circular import for no benefit;
        # RQ resolves the path when the job actually runs, in the worker
        # process.
        try:
            get_analysis_queue().enqueue(
                "offerleaks.worker.process_analysis",
                str(analysis.id),
                job_timeout=settings.analysis_job_timeout_seconds,
            )
        except Exception as exc:
            # The charge already committed but the job never entered the
            # queue -- refund (idempotent) and mark the analysis FAILED so
            # it doesn't sit in PENDING forever (the reconciliation sweep,
            # offerleaks/reconciliation.py, would also eventually catch
            # this via the pending timeout, but there's no reason to wait
            # for that when the failure is already known here), then
            # surface a 503 rather than returning a PENDING analysis that
            # will never process.
            logger.error("failed to enqueue analysis %s: %s", analysis.id, exc)
            await self._credits.refund_for_analysis(user_id=user.id, analysis_id=analysis.id)
            await self._analyses.set_status(
                analysis,
                AnalysisStatus.FAILED,
                error_message="We couldn't start processing this document. Please try again.",
            )
            await self._db.commit()
            raise QueueUnavailableError from exc

        return analysis

    async def get_owned_analysis(self, *, user: User, analysis_id: uuid.UUID) -> Analysis:
        analysis = await self._analyses.get_owned_by(analysis_id, user.id)
        if analysis is None:
            raise AnalysisNotFoundError
        return analysis

    async def list_analyses(
        self,
        *,
        user: User,
        limit: int,
        offset: int,
        status_filter: AnalysisStatus | None = None,
    ) -> tuple[list[Analysis], int]:
        """Version 5 dashboard/history: `user`'s own analyses, newest
        first. Ownership is always the authenticated `user`, never a
        client-supplied id (architecture.md §0.10) -- there is no
        equivalent method that takes an arbitrary user id."""
        return await self._analyses.list_owned_by(
            user.id, limit=limit, offset=offset, status_filter=status_filter
        )

    async def recheck_analysis(self, *, user: User, analysis_id: uuid.UUID) -> Analysis:
        """Version 5 "re-check": re-runs the OCR->AI pipeline for a past,
        already-terminal analysis against the same stored file, without
        asking the user to re-upload.

        Cost rule (documented decision -- the roadmap only specifies
        "re-check" as a capability, not its pricing, so this is the
        smallest reasonable engineering decision rather than an invented
        feature):

        - Free, iff (a) the AI prompt version hasn't changed since the
          source analysis ran (nothing that could change the outcome has
          changed, so re-running is a courtesy, not new work) AND (b) the
          source analysis's one allowed free re-check hasn't already been
          claimed (atomically enforced by
          `AnalysisRepository.try_claim_free_recheck`, safe under
          concurrent requests).
        - Charged the normal per-analysis cost otherwise -- either the
          prompt changed (a genuinely different pipeline run) or the free
          re-check was already used for this source.

        (b) exists specifically to close an uncontrolled-cost-exposure
        gap: without a cap, "free while the prompt is unchanged" would let
        a user re-trigger OCR+AI provider calls for the same document
        indefinitely at zero cost. Capping it to one free re-check per
        source analysis preserves the intent ("you already paid to have
        this exact pipeline run on this document once") while keeping the
        AI/OCR cost exposure bounded per paid unit of work.

        Raises `AnalysisNotFoundError` if `analysis_id` doesn't exist or
        isn't owned by `user`, `AnalysisNotReadyForRecheckError` if the
        source analysis hasn't reached a terminal state yet, and
        `InsufficientCreditsError`/`QueueUnavailableError` the same way
        `create_analysis` does for a charged re-check.
        """
        settings: Settings = get_settings()

        source = await self.get_owned_analysis(user=user, analysis_id=analysis_id)
        if source.status not in (
            AnalysisStatus.COMPLETE,
            AnalysisStatus.FAILED,
            AnalysisStatus.NEEDS_MANUAL_REVIEW,
        ):
            raise AnalysisNotReadyForRecheckError

        # Only attempt to claim the free slot if the prompt version still
        # matches -- claiming it for a charged (prompt-changed) re-check
        # would burn it for nothing, since the point is "one free re-run
        # of the exact pipeline that already ran."
        is_free = False
        if source.prompt_version == settings.ai_prompt_version:
            is_free = await self._analyses.try_claim_free_recheck(source.id)

        if not is_free:
            # Same fast-path-then-authoritative pattern as `create_analysis`:
            # a pre-check to fail fast, the real enforcement is the atomic
            # charge below inside the same transaction as the new Analysis
            # row.
            current_balance = await self._credits.get_balance(user.id)
            if current_balance < self._credits.cost_per_analysis:
                raise InsufficientCreditsError(
                    required=self._credits.cost_per_analysis, available=current_balance
                )

        analysis = await self._analyses.create(
            user_id=user.id,
            file_storage_key=source.file_storage_key,
            file_name=source.file_name,
            file_mime_type=source.file_mime_type,
            file_size_bytes=source.file_size_bytes,
            prompt_version=settings.ai_prompt_version,
            source_analysis_id=source.id,
        )

        if not is_free:
            try:
                await self._credits.charge_for_analysis(user_id=user.id, analysis_id=analysis.id)
            except InsufficientCreditsError:
                await self._db.rollback()
                raise
        await self._db.commit()

        try:
            get_analysis_queue().enqueue(
                "offerleaks.worker.process_analysis",
                str(analysis.id),
                job_timeout=settings.analysis_job_timeout_seconds,
            )
        except Exception as exc:
            logger.error("failed to enqueue re-check analysis %s: %s", analysis.id, exc)
            if is_free:
                # Give back the free slot -- the user got nothing for it.
                await self._analyses.release_free_recheck(source.id)
            else:
                await self._credits.refund_for_analysis(user_id=user.id, analysis_id=analysis.id)
            await self._analyses.set_status(
                analysis,
                AnalysisStatus.FAILED,
                error_message="We couldn't start re-checking this document. Please try again.",
            )
            await self._db.commit()
            raise QueueUnavailableError from exc

        return analysis


# Re-exported for routers that only need to catch validation errors without
# importing `file_validation`/`credit_service` directly.
__all__ = [
    "AnalysisNotFoundError",
    "AnalysisNotReadyForRecheckError",
    "AnalysisService",
    "AnalysisServiceError",
    "FileValidationError",
    "InsufficientCreditsError",
    "MalwareDetectedError",
    "MonthlyAnalysisLimitExceededError",
    "QueueUnavailableError",
    "ScanUnavailableForUploadError",
]
