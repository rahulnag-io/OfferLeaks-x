"""Structured private report model (M8: Structured Reporting + Reuse
Features -- Revised_ARCHITECTURE.md M8).

A `Report` is a user-submitted, structured complaint about a company,
offer (analysis), recruiter, or website -- private in this milestone
(M8 §"Explicitly deferred": no public visibility, no report feed, no
moderator UI). Reports are the only new table M8 introduces; personal
analytics and offer comparison are pure queries over existing tables
(`Analysis`/`Verdict`), not new schema.

Status lifecycle is intentionally small and forward-only:

    SUBMITTED --> UNDER_REVIEW --> VERIFIED
              \\--> UNDER_REVIEW --> REJECTED
              \\--> VERIFIED
              \\--> REJECTED

`VERIFIED` and `REJECTED` are terminal -- once a report has been decided,
it does not flip back, which is what makes "a rejected report never
silently pollutes the internal reputation score" hold *structurally*: a
report can only ever contribute to reputation by reaching `VERIFIED`,
and once there it cannot un-become verified through some other path.
This is the smallest reasonable engineering decision for a private,
low-volume-review workflow (M8 §5: founder review via direct
queries/internal tooling, not a full moderator UI) -- a correction
workflow (re-opening a decided report) is not required by the roadmap
and is not implemented here.

Duplicate detection (`services/report_duplicate_detection.py`) never
blocks or merges a submission -- every report a user submits is
persisted (so the record is truthful and auditable), but a report
flagged `is_duplicate=True` is permanently excluded from the internal
reputation count (see `services/report_service.py::_recompute_company_reputation`),
regardless of what status it's later moved to. This is what satisfies
the roadmap's "prevent duplicate reports from unnecessarily multiplying
internal reputation influence" without discarding a legitimate,
distinct-but-similar report a real user actually filed.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from offerleaks.core.db import Base


class ReportTargetType(enum.StrEnum):
    """What kind of thing this report is about. `COMPANY`/`OFFER` resolve
    to `company_id`/`analysis_id` respectively (an offer's report is
    additionally attributed to its resolved company, if any, so it can
    still feed the M7 company profile). `RECRUITER`/`WEBSITE` are
    free-text-only targets (M8's roadmap requires these categories but
    the product has no first-class Recruiter/Website entity yet) --
    their identifying detail lives in `target_detail`.
    """

    COMPANY = "company"
    OFFER = "offer"
    RECRUITER = "recruiter"
    WEBSITE = "website"


class ReportReason(enum.StrEnum):
    """Categorized reasons, matching the kinds of scam patterns already
    known to the product (`models/scam_pattern.py`) so the taxonomy the
    user picks from is consistent with what the rules engine/AI already
    look for -- not an arbitrary parallel vocabulary.
    """

    UPFRONT_PAYMENT_REQUEST = "upfront_payment_request"
    FAKE_OR_UNREGISTERED_COMPANY = "fake_or_unregistered_company"
    IDENTITY_OR_DOCUMENT_THEFT = "identity_or_document_theft"
    UNREALISTIC_SALARY_OR_OFFER = "unrealistic_salary_or_offer"
    PRESSURE_OR_URGENCY_TACTICS = "pressure_or_urgency_tactics"
    IMPERSONATION_OF_REAL_COMPANY = "impersonation_of_real_company"
    NO_INTERVIEW_OR_UNVERIFIABLE_PROCESS = "no_interview_or_unverifiable_process"
    SUSPICIOUS_CONTACT_CHANNEL = "suspicious_contact_channel"
    OTHER = "other"


class ReportStatus(enum.StrEnum):
    SUBMITTED = "submitted"
    UNDER_REVIEW = "under_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


# Statuses a report may still be actively moving through -- i.e. not yet
# terminal. Used by `ReportRepository.try_transition_status` to build its
# `WHERE status IN (...)` guard.
NON_TERMINAL_STATUSES = frozenset({ReportStatus.SUBMITTED, ReportStatus.UNDER_REVIEW})

# Only a report that reached this status (and isn't a flagged duplicate)
# counts toward the internal-only company reputation signal.
REPUTATION_ELIGIBLE_STATUS = ReportStatus.VERIFIED


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )

    # Ownership -- reports are private to the submitting user (M8 §10/§15:
    # "reports must not be exposed to other users"). CASCADE: a deleted
    # user's own private reports have no reason to survive them.
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    target_type: Mapped[ReportTargetType] = mapped_column(
        Enum(
            ReportTargetType,
            name="report_target_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )

    # The resolved company this report is about/attributed to, if any --
    # required for `target_type=COMPANY`, derived from the analysis's own
    # `company_id` for `target_type=OFFER` where resolvable. `NULL` for a
    # RECRUITER/WEBSITE report with no resolvable company, or a COMPANY/
    # OFFER report about a company that never resolved one (M7's honest
    # "nothing to resolve" case) -- an unresolved report is still stored
    # (so the user's submission is never silently dropped), it simply
    # cannot contribute to any company's reputation signal.
    # `SET NULL` on delete, same reasoning as `Analysis.company_id`:
    # `Company` rows are shared reference data, deleting one must never
    # cascade into deleting a user's private report.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # The specific offer (`Analysis`) this report is about, for
    # `target_type=OFFER` -- reuses the existing analysis/verdict context
    # rather than asking the user to re-describe an offer the system
    # already has (M8 §"Use the existing verdict/company/offer context").
    # `SET NULL` on delete: deleting the underlying analysis should not
    # delete the user's report about it, only detach the reference.
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Free-text identifying detail for RECRUITER/WEBSITE targets (a name,
    # a URL, an email) -- there is no first-class entity for either yet,
    # so this is the only "what/who" identifier those two target types
    # carry. Optional for COMPANY/OFFER, which already have `company_id`/
    # `analysis_id`.
    target_detail: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # list[str] of `ReportReason` values -- JSON, not a join table: the
    # set is small, fixed, and never queried/filtered by individual
    # reason server-side in v1 (same "avoid an abstraction that isn't
    # justified yet" reasoning as `Verdict.red_flags`).
    reasons: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    description: Mapped[str] = mapped_column(Text, nullable=False)

    # Deterministic, lowercased/whitespace-collapsed form of `description`
    # (`services/report_duplicate_detection.py::normalize_report_text`),
    # computed once at submission time and persisted so duplicate-window
    # queries never have to re-normalize every candidate row's
    # description on every read.
    description_normalized: Mapped[str] = mapped_column(Text, nullable=False)

    status: Mapped[ReportStatus] = mapped_column(
        Enum(
            ReportStatus,
            name="report_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ReportStatus.SUBMITTED,
        server_default=ReportStatus.SUBMITTED.value,
        index=True,
    )

    # Set at submission time by `services/report_duplicate_detection.py`
    # against other reports for the same company within the configured
    # window. Never recomputed later -- a report's duplicate-ness is a
    # property of what was already on file *at the moment it was filed*,
    # not something that should silently change as more reports arrive
    # after it.
    is_duplicate: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    duplicate_of_report_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("reports.id", ondelete="SET NULL"), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), index=True
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
