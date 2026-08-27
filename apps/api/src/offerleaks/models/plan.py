"""Plan/entitlement models (M6: Trust Verdict + Monetization Foundation).

`Plan` is the billing-relevant shape of a tier (Free/Pro): what it costs,
and the two numeric caps that gate the existing credit/analysis flow
directly (`monthly_credit_grant`, `monthly_analysis_limit`). Those two
stay first-class typed columns -- not entries in `PlanEntitlement` --
because `EntitlementService`/`AnalysisService` branch on them with real
business logic (a null limit means "unlimited"; a null column meaning
that would be worse than an explicit nullable int).

`PlanEntitlement` is a generic (plan, key) -> value store for *feature
flags* that don't need bespoke columns or logic yet -- e.g. a future
"priority_queue" or "watch_alerts" flag for M9's Company Watch can be
added as a row, no migration required. This is deliberately the only
place in the system that uses a generic key/value shape; everything else
stays typed columns per architecture.md §0.3's "avoid abstractions that
aren't justified yet."
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from offerleaks.core.db import Base

# Well-known plan keys. Not an enum column (unlike `AnalysisStatus`) --
# plans are DB rows, not a fixed type, so a future third tier is a new
# row + migration-free, not a new enum member + migration. These
# constants exist only so code that needs to refer to "the free plan"
# specifically (e.g. the entitlement-resolution fallback) has one place
# to change the key string.
FREE_PLAN_KEY = "free"
PRO_PLAN_KEY = "pro"


class Plan(Base):
    __tablename__ = "plans"
    __table_args__ = (UniqueConstraint("key", name="uq_plans_key"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    key: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)

    # Credits granted once per billing period for an ACTIVE subscription
    # to this plan (see `models/usage_ledger.py` for the idempotency
    # guard around applying this). The free plan's initial 3-credit grant
    # (Version 4, `credit_initial_grant` in config) is a one-time signup
    # bonus, not a recurring plan grant -- this column is 0 for `free`.
    monthly_credit_grant: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    # Null = unlimited. Enforced by `EntitlementService` in addition to
    # (not instead of) the existing per-analysis credit charge -- see
    # that module's docstring for why both checks exist.
    monthly_analysis_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # Smallest currency unit (paise, since architecture.md §5/M6 prices in
    # ₹ via Razorpay) -- avoids float rounding on money, same reasoning as
    # `CreditBalance.balance` being a plain integer.
    price_amount_minor: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    price_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="INR")

    # Razorpay's own Plan id (`plan_...`), created once out-of-band in
    # the Razorpay dashboard/API and pasted in here -- this row is the
    # mapping from "our plan" to "their plan," never the other way
    # around (architecture.md §0.10: never trust a client-supplied
    # authoritative id). Null for the free plan, which has no
    # corresponding Razorpay plan.
    razorpay_plan_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class PlanEntitlement(Base):
    """A single (plan, key) -> value feature flag. See module docstring."""

    __tablename__ = "plan_entitlements"
    __table_args__ = (
        UniqueConstraint("plan_id", "key", name="uq_plan_entitlements_plan_id_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    key: Mapped[str] = mapped_column(String(100), nullable=False)
    # Stored as a string deliberately -- callers (`EntitlementService`)
    # own interpreting a given key's value ("true"/"false", a number,
    # etc.), matching how `AnalysisFailureReason` is "a plain column, not
    # a type the DB enforces" for the same not-worth-a-migration reason.
    value: Mapped[str] = mapped_column(String(500), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
