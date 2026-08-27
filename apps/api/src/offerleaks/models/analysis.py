"""Analysis & Verdict models (Version 3: Upload -> OCR -> AI Verdict;
extended in Version 5 with `source_analysis_id` for dashboard re-checks).

An `Analysis` is one uploaded offer letter belonging to one user. A
`Verdict` is the AI's structured output for that analysis, one-to-one,
only present once `status` reaches `COMPLETE`.

`company_id` (added in M7, see `models/company.py`) links an analysis to
the shared, cached `Company` profile resolved from its sender domain/
extracted company name -- best-effort and set after the fact by the
worker, never required for an analysis to complete.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from offerleaks.core.db import Base


class AnalysisStatus(enum.StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETE = "complete"
    FAILED = "failed"
    # AI provider errored/timed out after its retry (§0.6 "Fallback
    # strategy"): never fabricate a low-confidence verdict, surface this
    # instead so a human can look at it.
    NEEDS_MANUAL_REVIEW = "needs_manual_review"


class AnalysisFailureReason(enum.StrEnum):
    """Internal-only category for *why* an analysis ended up FAILED or
    NEEDS_MANUAL_REVIEW -- never returned to the client (architecture.md
    §0.11: no internal error detail leaked to the end user; `error_message`
    is the user-facing string, this is for logs/ops/debugging). Stored as
    a plain `String`, not a Postgres `Enum` type like `status` -- this is
    an internal diagnostic label, never queried/filtered/validated against
    client input the way `status` is, so a migration-free-to-extend plain
    column fits better (same reasoning as `prompt_version` being a plain
    `String` rather than an `Enum`).
    """

    PENDING_TIMEOUT = "pending_timeout"
    PROCESSING_TIMEOUT = "processing_timeout"
    STORAGE_UNAVAILABLE = "storage_unavailable"
    OCR_FAILED = "ocr_failed"
    AI_FAILED = "ai_failed"
    WORKER_CRASH = "worker_crash"


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    # Set only for an analysis created by "re-check" (Version 5). Points at
    # the original analysis this one re-runs the pipeline for. `SET NULL`
    # on delete (not CASCADE): a re-check is its own independent, already-
    # charged-or-not Analysis row -- deleting the source it was re-checked
    # from should not cascade-delete the re-check itself, just detach the
    # link (architecture.md §0.9's ANALYSIS entity has no lifecycle tie
    # between the two beyond provenance).
    source_analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # M7: the resolved `Company` this analysis's document was attributed
    # to, if any (best-effort, set by the worker after the deterministic
    # extraction/resolution step -- see `worker.py`). `NULL` until that
    # step runs, and permanently `NULL` for an analysis with no
    # resolvable sender domain or company name at all (an honest
    # "nothing to resolve," distinct from a resolution that ran and
    # found `NOT_FOUND`/`INSUFFICIENT_EVIDENCE`, which still has a row
    # here). `SET NULL` on delete: `Company` rows are shared, long-lived
    # reference data across many users' analyses (M7 "cached across
    # users"), so deleting one must never cascade into deleting
    # unrelated analyses -- only detach the reference, same reasoning as
    # `source_analysis_id` above.
    company_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("companies.id", ondelete="SET NULL"), nullable=True, index=True
    )

    # Whether this analysis's *one* allowed free re-check (see
    # `AnalysisService.recheck_analysis`) has been claimed. Lives on the
    # source analysis, not the re-check -- claimed via a single atomic
    # `UPDATE ... WHERE free_recheck_claimed = false RETURNING ...`
    # (`AnalysisRepository.try_claim_free_recheck`), the same
    # conditional-UPDATE pattern `CreditRepository.try_consume` uses, so
    # concurrent re-check requests can't both land the free one.
    free_recheck_claimed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    # Storage key the original file lives under in the S3-compatible
    # bucket (never served directly, never trusted as safe to render --
    # §0.11). The original is retained (not just the extracted text) so a
    # future OCR provider/pipeline improvement can re-process without
    # asking the user to re-upload (§0.13).
    file_storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    file_mime_type: Mapped[str] = mapped_column(String(100), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[AnalysisStatus] = mapped_column(
        Enum(
            AnalysisStatus,
            name="analysis_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=AnalysisStatus.PENDING,
        server_default=AnalysisStatus.PENDING.value,
        index=True,
    )

    # Stamped atomically together with the PENDING -> PROCESSING
    # transition (`AnalysisRepository.try_start_processing`). Distinct
    # from `created_at` because a job can sit queued for a while before a
    # worker actually picks it up -- this is "when work on it actually
    # began," which is what the stuck-analysis reconciliation sweep
    # (`offerleaks/reconciliation.py`) needs for its processing-timeout
    # check. `NULL` until then, and for any analysis that never left
    # PENDING.
    processing_started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, index=True
    )

    # See `AnalysisFailureReason`. Set alongside `error_message` on every
    # FAILED/NEEDS_MANUAL_REVIEW transition, `NULL` otherwise.
    failure_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # Which prompt template produced (or would have produced) this
    # analysis's verdict -- persisted even on failure so a failed job's
    # prompt version is still known if it's retried after a prompt change.
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)

    # Set on FAILED / NEEDS_MANUAL_REVIEW. Deliberately a short, typed
    # category message -- never the raw provider exception (§0.11 logging:
    # no sensitive payload contents, and no internal error strings leaked
    # to the client).
    error_message: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Verdict(Base):
    __tablename__ = "verdicts"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    analysis_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # one-to-one with Analysis
        index=True,
    )

    risk_score: Mapped[int] = mapped_column(Integer, nullable=False)
    # list[RedFlag] (schemas.ai.RedFlag), stored as the provider returned
    # it -- JSONB on Postgres via the generic JSON type. M6: each flag may
    # now carry an `evidence_quote` (see schemas/ai.py), still stored here
    # unchanged -- this column's shape is "whatever RedFlag currently is,"
    # not duplicated per field.
    red_flags: Mapped[list[dict[str, str]]] = mapped_column(JSON, nullable=False)
    reasoning: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)

    # --- M6: Trust Verdict + Monetization Foundation ---
    # list[schemas.patterns.MatchedPattern], the deterministic output of
    # `RulesEngine.match` against the OCR'd document text -- independent
    # of, and stored alongside, the AI's own `red_flags`. Server-default
    # '[]' so the (nullable-free) column back-fills cleanly for any
    # pre-M6 verdict row touched by the migration.
    matched_patterns: Mapped[list[dict[str, str]]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    # list[str], 2-4 short next-step strings. Deliberately rule-based
    # (`services/rules_engine.py::recommended_actions_for`), not an AI
    # output -- Revised_ARCHITECTURE.md M6 calls this out explicitly as
    # "near-zero marginal cost" precisely because it's not a model call.
    recommended_actions: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list, server_default="[]"
    )
    # Fraction (0.0-1.0) of this verdict's `red_flags` that carry a
    # non-null `evidence_quote`. Computed once, server-side, when the
    # verdict is created (`RulesEngine.evidence_coverage`) rather than
    # recomputed on every read -- it's a property of the verdict as
    # produced, not a live derived value.
    evidence_coverage: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
