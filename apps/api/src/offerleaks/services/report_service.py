"""Report business logic (M8: Structured Reporting + Reuse Features).

The one reusable boundary every entry point (the `POST /reports` router,
and any future internal-review tooling) goes through -- routers never
touch `ReportRepository` directly, matching the existing service-
ownership convention (architecture.md §0.3, same as
`CompanyProfileService`/`EntitlementService`).

Three responsibilities live here, deliberately not split further (M8
§8: "create only the abstractions justified by the requirements"):

1. **Submission** -- validates target/company/analysis context, computes
   duplicate detection, persists the report.
2. **Status transitions** -- the only place `Report.status` is ever
   written after creation, always via the repository's atomic
   conditional UPDATE (retry/concurrency-safe by construction).
3. **Internal reputation aggregation** -- extends the M7 `CompanySignal`
   row (`_recompute_company_reputation`) whenever a transition could have
   changed the verified-report count. Always a full re-count, never an
   incremental adjustment (see `ReportRepository.count_verified_non_duplicate`
   docstring) -- this is what keeps double-counting structurally
   impossible rather than merely tested-for.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.core.config import Settings, get_settings
from offerleaks.models.report import (
    Report,
    ReportReason,
    ReportStatus,
    ReportTargetType,
)
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.repositories.report_repository import ReportRepository
from offerleaks.services.report_duplicate_detection import (
    is_duplicate_description,
    normalize_report_text,
)

logger = logging.getLogger(__name__)

_MIN_DESCRIPTION_LENGTH = 10
_MAX_DESCRIPTION_LENGTH = 5000
_MAX_REASONS = 6

# Explicit, small state machine -- see `models/report.py` module
# docstring for why terminal states never transition back out.
_ALLOWED_TRANSITIONS: dict[ReportStatus, frozenset[ReportStatus]] = {
    ReportStatus.UNDER_REVIEW: frozenset({ReportStatus.SUBMITTED}),
    ReportStatus.VERIFIED: frozenset({ReportStatus.SUBMITTED, ReportStatus.UNDER_REVIEW}),
    ReportStatus.REJECTED: frozenset({ReportStatus.SUBMITTED, ReportStatus.UNDER_REVIEW}),
}


class ReportServiceError(Exception):
    """Base class for all report-service failures. Routers map this to 4xx."""


class ReportValidationError(ReportServiceError):
    pass


class ReportNotFoundError(ReportServiceError):
    pass


class InvalidStatusTransitionError(ReportServiceError):
    def __init__(self, *, current: ReportStatus, requested: ReportStatus) -> None:
        super().__init__(f"cannot transition report from {current.value!r} to {requested.value!r}")
        self.current = current
        self.requested = requested


@dataclass(frozen=True, slots=True)
class ReportSubmission:
    target_type: ReportTargetType
    reasons: list[ReportReason]
    description: str
    company_id: uuid.UUID | None = None
    analysis_id: uuid.UUID | None = None
    target_detail: str | None = None


class ReportService:
    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self._db = db
        self._reports = ReportRepository(db)
        self._analyses = AnalysisRepository(db)
        self._companies = CompanyRepository(db)
        self._settings = settings or get_settings()

    # --- Submission ---

    async def submit_report(self, *, user: User, submission: ReportSubmission) -> Report:
        self._validate_submission(submission)

        company_id = submission.company_id
        analysis_id: uuid.UUID | None = None

        if submission.target_type == ReportTargetType.OFFER:
            if submission.analysis_id is None:
                raise ReportValidationError("analysis_id is required for an offer report")
            # Ownership check: a report can only be filed against an
            # offer the reporting user actually owns (M8 §10: "prevent
            # cross-user access... derive identity from the verified
            # authentication context"). Reuses `get_owned_by` the exact
            # same way every other owner-scoped read in the codebase does
            # -- 404-shaped ("not found"), never a 403 that would
            # confirm another user's analysis exists.
            analysis = await self._analyses.get_owned_by(submission.analysis_id, user.id)
            if analysis is None:
                raise ReportValidationError("analysis not found")
            analysis_id = analysis.id
            # Reuse the offer's already-resolved company context (M8
            # §"Use the existing verdict/company/offer context... rather
            # than requiring users to recreate information the system
            # already knows") -- an explicit `company_id` from the client
            # is never trusted over this for an OFFER report.
            company_id = analysis.company_id
        elif submission.target_type == ReportTargetType.COMPANY:
            if company_id is None:
                raise ReportValidationError("company_id is required for a company report")
            company = await self._companies.get_by_id(company_id)
            if company is None:
                raise ReportValidationError("company not found")

        normalized = normalize_report_text(submission.description)

        is_duplicate = False
        duplicate_of_id: uuid.UUID | None = None
        if company_id is not None:
            is_duplicate, duplicate_of_id = await self._detect_duplicate(
                company_id=company_id, normalized_description=normalized
            )

        report = Report(
            user_id=user.id,
            target_type=submission.target_type,
            company_id=company_id,
            analysis_id=analysis_id,
            target_detail=submission.target_detail,
            reasons=[reason.value for reason in submission.reasons],
            description=submission.description,
            description_normalized=normalized,
            status=ReportStatus.SUBMITTED,
            is_duplicate=is_duplicate,
            duplicate_of_report_id=duplicate_of_id,
        )
        report = await self._reports.create(report)
        await self._db.commit()

        logger.info(
            "report submitted id=%s user_id=%s target_type=%s company_id=%s is_duplicate=%s",
            report.id,
            user.id,
            submission.target_type.value,
            company_id,
            is_duplicate,
        )
        return report

    def _validate_submission(self, submission: ReportSubmission) -> None:
        description = submission.description.strip()
        if len(description) < _MIN_DESCRIPTION_LENGTH:
            raise ReportValidationError(
                f"description must be at least {_MIN_DESCRIPTION_LENGTH} characters"
            )
        if len(description) > _MAX_DESCRIPTION_LENGTH:
            raise ReportValidationError(
                f"description must be at most {_MAX_DESCRIPTION_LENGTH} characters"
            )
        if not submission.reasons:
            raise ReportValidationError("at least one reason is required")
        if len(submission.reasons) > _MAX_REASONS:
            raise ReportValidationError(f"at most {_MAX_REASONS} reasons are allowed")

        if submission.target_type in (ReportTargetType.RECRUITER, ReportTargetType.WEBSITE):
            if not submission.target_detail or not submission.target_detail.strip():
                raise ReportValidationError(
                    f"target_detail is required for a {submission.target_type.value} report"
                )

    async def _detect_duplicate(
        self, *, company_id: uuid.UUID, normalized_description: str
    ) -> tuple[bool, uuid.UUID | None]:
        window_start = datetime.now(UTC) - timedelta(
            hours=self._settings.report_duplicate_window_hours
        )
        candidates = await self._reports.find_recent_for_company(company_id, since=window_start)
        for candidate in candidates:
            if is_duplicate_description(
                normalized_description,
                candidate.description_normalized,
                threshold=self._settings.report_duplicate_similarity_threshold,
            ):
                return True, candidate.id
        return False, None

    # --- Reads ---

    async def get_owned_report(self, *, user: User, report_id: uuid.UUID) -> Report:
        report = await self._reports.get_owned_by(report_id, user.id)
        if report is None:
            raise ReportNotFoundError
        return report

    async def list_my_reports(
        self, *, user: User, limit: int, offset: int
    ) -> tuple[list[Report], int]:
        return await self._reports.list_owned_by(user.id, limit=limit, offset=offset)

    # --- Status transitions ---

    async def transition_status(
        self, *, report_id: uuid.UUID, to_status: ReportStatus
    ) -> Report:
        """Internal-tooling operation (M8 §5: "founder review may
        continue through internal tooling... rather than requiring a
        public or dedicated moderator UI") -- gated at the router layer
        by `require_roles(Role.ADMIN, Role.MODERATOR)`, reusing the
        existing RBAC scaffold rather than inventing a new one.
        """
        allowed_from = _ALLOWED_TRANSITIONS.get(to_status)
        if allowed_from is None:
            # to_status == SUBMITTED, or an unrecognized value -- nothing
            # ever transitions *into* SUBMITTED (it's only the creation
            # state).
            existing = await self._reports.get_by_id(report_id)
            current = existing.status if existing is not None else ReportStatus.SUBMITTED
            raise InvalidStatusTransitionError(current=current, requested=to_status)

        updated = await self._reports.try_transition_status(
            report_id=report_id, allowed_from=allowed_from, to_status=to_status
        )
        if updated is None:
            existing = await self._reports.get_by_id(report_id)
            if existing is None:
                raise ReportNotFoundError
            if existing.status == to_status:
                # Already in the target state -- safe no-op under retry/
                # duplicate-delivery, not an error (M8 §13).
                await self._db.commit()
                return existing
            raise InvalidStatusTransitionError(current=existing.status, requested=to_status)

        # Only a transition into/out of VERIFIED can possibly change the
        # verified-report count, but recomputing unconditionally (rather
        # than branching on `to_status`) means this stays correct even if
        # the small state machine above ever grows a new path into or
        # out of VERIFIED -- the recompute itself is a cheap, idempotent
        # full re-count (see its docstring), so there's no cost reason to
        # special-case which transitions "should" trigger it.
        if updated.company_id is not None:
            await self._recompute_company_reputation(updated.company_id)

        await self._db.commit()
        return updated

    async def _recompute_company_reputation(self, company_id: uuid.UUID) -> None:
        count = await self._reports.count_verified_non_duplicate(company_id)
        score = self._reputation_score_for(count)
        await self._companies.set_report_reputation_signal(
            company_id=company_id,
            verified_report_count=count,
            internal_reputation_score=score,
        )

    def _reputation_score_for(self, verified_report_count: int) -> int | None:
        """Deterministic 0-100 internal concern score. `None` (not `0`)
        when there are zero verified reports -- distinguishing "no
        signal yet" from "checked and found clean," the same tri-state
        convention `CompanySignal`'s other nullable fields already use.
        """
        if verified_report_count <= 0:
            return None
        saturation = max(1, self._settings.report_reputation_score_saturation_count)
        return min(100, round((verified_report_count / saturation) * 100))
