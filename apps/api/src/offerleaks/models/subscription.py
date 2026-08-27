"""Subscription model (M6: Trust Verdict + Monetization Foundation).

One `Subscription` row per user (unique on `user_id`) -- a user has at
most one subscription at a time, upgraded/downgraded/canceled in place
rather than modeled as a history of rows. Historical billing events
still have an audit trail: `WebhookEvent` (every provider event, raw)
and `UsageLedgerEntry` (every credit grant this subscription caused) are
both append-only, so "what happened to this subscription over time" is
answerable without `Subscription` itself needing to be append-only.

A user with no `Subscription` row is implicitly on the free plan --
`EntitlementService` is the single place that resolves "current plan for
this user," and it encodes that fallback (see that module).
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from offerleaks.core.db import Base


class SubscriptionStatus(enum.StrEnum):
    # Razorpay subscription created but not yet authorized/charged
    # (waiting on the customer to complete checkout).
    CREATED = "created"
    ACTIVE = "active"
    # A renewal charge failed; Razorpay will retry per its own dunning
    # schedule before eventually canceling. Entitlements are *not*
    # downgraded immediately on PAST_DUE -- only on CANCELED/EXPIRED --
    # to tolerate a transient card failure without punishing the user
    # for a retry Razorpay hasn't finished yet.
    PAST_DUE = "past_due"
    CANCELED = "canceled"
    EXPIRED = "expired"


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (UniqueConstraint("user_id", name="uq_subscriptions_user_id"),)

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )

    # Razorpay's own subscription id (`sub_...`). Unique + indexed:
    # every inbound webhook is looked up by this, never by our own `id`
    # (architecture.md §0.10 -- the provider's id is the only thing a
    # webhook payload can be trusted to identify a subscription by).
    razorpay_subscription_id: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True, index=True
    )
    razorpay_customer_id: Mapped[str | None] = mapped_column(String(100), nullable=True)

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(
            SubscriptionStatus,
            name="subscription_status",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
        default=SubscriptionStatus.CREATED,
        server_default=SubscriptionStatus.CREATED.value,
    )

    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cancel_at_period_end: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
