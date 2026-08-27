"""Usage ledger (M6: Trust Verdict + Monetization Foundation).

Distinct from `CreditTransaction` (Version 4): `CreditTransaction` is the
ledger for *credit balance* mutations (grant/consume/refund), keyed for
idempotency by `(analysis_id, type)`. A subscription-renewal credit grant
has no `analysis_id` to key off of -- it's keyed by *billing period*
instead, which is what this table is for.

`UsageLedgerEntry` is the idempotency guard for "has this subscription's
current billing period already been granted its monthly credits?" via
the unique constraint below. Without it, a redelivered/retried Razorpay
webhook for the same renewal would grant the monthly credit bundle twice
-- the same class of bug `CreditTransaction`'s unique constraint prevents
for analysis charges, applied to the recurring-grant case instead.

Every row here that grants credits also writes a corresponding
`CreditTransaction` (type=GRANT, analysis_id=None) via
`CreditService.grant_initial_credits`'s underlying repository call --
this table is the idempotency key *and* audit trail for "why," the
credit ledger stays the single source of truth for "what the balance
is."
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from offerleaks.core.db import Base


class UsageLedgerEntry(Base):
    __tablename__ = "usage_ledger"
    __table_args__ = (
        # At most one grant per (subscription, billing period). Postgres
        # does not constrain NULLs against each other, so this only
        # actually guards subscription-linked rows -- which is the only
        # kind this table has in v1 (see module docstring).
        UniqueConstraint(
            "subscription_id", "period_key", name="uq_usage_ledger_subscription_period"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("subscriptions.id", ondelete="CASCADE"), nullable=True, index=True
    )

    # Razorpay's billing-cycle identifier where available (falls back to
    # an ISO period string derived from `current_period_start` if the
    # webhook payload doesn't carry one) -- an opaque string key, not a
    # parsed date, since its only job is "unique per renewal."
    period_key: Mapped[str] = mapped_column(String(100), nullable=False)

    credits_granted: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
