"""Company entity + cached company signal models (M7: Company Signal &
Reputation, lean version -- Revised_ARCHITECTURE.md M7).

Two tables, matching the roadmap's explicit scope:

- `Company` is the resolved *entity* -- one row per normalized company/
  domain identity, shared across every user who ever uploads an offer
  from that company. It carries no reputation data itself.
- `CompanySignal` is the *cached, refreshable* deterministic signal set
  for that entity: domain age, website reachability, email-domain-match,
  and a 2-level verification status, plus an honest "insufficient
  evidence" state. One row per company (`company_id` is unique) --
  refreshed *in place* on the existing background-worker cadence, not
  appended to a history table (reputation trend history is explicitly
  deferred to M9, once Watch gives it more than one data point to plot).

Postgres is the authoritative, restart-surviving store for both; Redis
(`services/company_profile_service.py`) is an acceleration cache in
front of them, never a second source of truth.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from offerleaks.core.db import Base


class CompanyVerificationStatus(enum.StrEnum):
    """The roadmap calls for a "2-level verification status: Found /
    Not Found" as the fundamental, always-visible signal -- but a
    provider outage or a company with genuinely no resolvable identity
    must never be silently collapsed into a fabricated `NOT_FOUND`
    (M7 §14/§27: "never convert provider failure into... a false
    negative"). `INSUFFICIENT_EVIDENCE` is that explicit third state:
    it is not part of the 2-level badge shown to a Free user (which only
    ever renders as Found/Not Found/Checking), but it is what
    `verification_status` actually holds whenever the system doesn't yet
    have enough to honestly say either way.
    """

    FOUND = "found"
    NOT_FOUND = "not_found"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ProviderCheckOutcome(enum.StrEnum):
    """Per-signal provider-call outcome, kept for observability only --
    never returned to the client (M7 §16: log failure category, but
    §11/§15 forbid exposing raw provider detail). Lets
    `CompanySignal.domain_age_days` being `NULL` be told apart from
    "we checked and there genuinely is no registration record" after
    the fact, without storing the raw WHOIS/RDAP payload anywhere.
    """

    OK = "ok"
    NOT_CONFIGURED = "not_configured"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    RATE_LIMITED = "rate_limited"
    MALFORMED_RESPONSE = "malformed_response"
    NO_RECORD = "no_record"


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )

    # The single deterministic identity key every lookup joins on --
    # `services/company_normalization.py::resolve_identity_key` is the
    # only place allowed to compute it, so "equivalent representations
    # don't create duplicate company records" (M7 requirement) holds by
    # construction rather than by every caller normalizing consistently
    # on their own. Prefixed with the resolution basis ("domain:" or
    # "name:") so a domain-based and a name-based key can never collide
    # even if the raw strings happened to coincide.
    normalized_key: Mapped[str] = mapped_column(
        String(320), unique=True, nullable=False, index=True
    )

    # Best-known normalized domain for this company, if resolution had
    # one to work with. Indexed on its own (in addition to being folded
    # into `normalized_key`) because "efficient lookup by normalized
    # domain" is called out explicitly in M7 §9/§24.
    domain: Mapped[str | None] = mapped_column(String(255), nullable=True, index=True)

    # Best-known display name, if the deterministic extraction step
    # (`services/company_extraction.py`) found one. Purely informational
    # -- never part of `normalized_key` when a domain is available,
    # since a domain is the more reliable identity signal.
    company_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CompanySignal(Base):
    __tablename__ = "company_signals"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,  # one signal row per company, refreshed in place
        index=True,
    )

    verification_status: Mapped[CompanyVerificationStatus] = mapped_column(
        Enum(
            CompanyVerificationStatus,
            name="company_verification_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=CompanyVerificationStatus.INSUFFICIENT_EVIDENCE,
        server_default=CompanyVerificationStatus.INSUFFICIENT_EVIDENCE.value,
    )

    # --- Advanced signals (Pro-gated at the API layer, never here --
    # this table has no notion of plans; gating is `EntitlementService`'s
    # job, applied when the API response is built). ---
    domain_age_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    domain_registered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    domain_age_check: Mapped[ProviderCheckOutcome] = mapped_column(
        Enum(
            ProviderCheckOutcome,
            name="provider_check_outcome",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ProviderCheckOutcome.NOT_CONFIGURED,
        server_default=ProviderCheckOutcome.NOT_CONFIGURED.value,
    )

    # Tri-state on purpose: `True`/`False` is a real, evidenced result;
    # `NULL` means "we don't honestly know" (timeout, network failure,
    # no domain to check at all) -- never coerced to `False` (M7 §14:
    # "do not convert an operational failure into a false negative").
    website_reachable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    website_reachability_check: Mapped[ProviderCheckOutcome] = mapped_column(
        Enum(
            ProviderCheckOutcome,
            name="provider_check_outcome",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=ProviderCheckOutcome.NOT_CONFIGURED,
        server_default=ProviderCheckOutcome.NOT_CONFIGURED.value,
    )

    # Whether the sender email domain extracted from the analyzed
    # document matches this company's resolved domain. `NULL` when there
    # was no sender domain, no resolved company domain, or both --
    # `False` is reserved for an actual, evidenced mismatch.
    email_domain_match: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # When this row's signals were last (re)computed -- the "last
    # checked" timestamp the frontend displays (M7 §12). Distinct from
    # `updated_at`, which also ticks on administrative/company-identity
    # edits unrelated to a signal refresh (there are none yet in v1, but
    # keeping the two independent avoids coupling them later).
    last_checked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # Fraction (0.0-1.0) of the signals above that were actually
    # evidenced (not `NOT_CONFIGURED`/failed) at last check -- used only
    # to help `CompanyProfileService` decide the overall
    # `verification_status`, not surfaced as its own UI element.
    evidence_ratio: Mapped[float] = mapped_column(
        Float, nullable=False, default=0.0, server_default="0.0"
    )

    # --- M8: Structured Reporting + Reuse Features ---
    # Internal-only community-signal contribution, extending this same
    # signal row rather than creating a second/competing reputation
    # table (M8 §8/§20: "must extend the existing M7 company-profile
    # architecture"). Both fields are populated exclusively by
    # `services/report_service.py::_recompute_company_reputation`, always
    # via a full re-count of `reports` rows (never an incremental
    # +1/-1) -- so re-running the recompute after a retry, a duplicate
    # webhook-style redelivery, or repeated worker processing always
    # converges on the same correct value instead of compounding an
    # error (M8 §13: "duplicate processing does not double-count
    # contributions"). Neither field is ever serialized into
    # `schemas/company.py::CompanyProfileResponse` -- that is the one
    # enforcement point for "report-derived reputation is not public"
    # (M8 §"Explicitly deferred" / §15).
    verified_report_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Deterministic 0-100 "internal concern score" derived from
    # `verified_report_count` (see `ReportService._reputation_score_for`)
    # -- `NULL` means "no verified reports on file yet," not "zero
    # concern," matching this table's existing tri-state convention for
    # every other nullable signal (M7's `website_reachable` docstring
    # above). A product signal for future use (M9+), not a public score.
    internal_reputation_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )

    __table_args__ = (UniqueConstraint("company_id", name="uq_company_signals_company_id"),)
