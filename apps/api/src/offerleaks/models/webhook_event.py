"""Inbound payment-provider webhook events (M6 billing).

This table is the idempotency guard for the *entire* webhook pipeline,
one layer beneath `UsageLedgerEntry`'s renewal-specific guard:
`(provider, provider_event_id)` is unique, and every webhook handler
call inserts a row here (via `WebhookRepository.record_once`, same
insert-inside-a-SAVEPOINT pattern as
`CreditRepository.record_transaction_once`) *before* doing anything else
-- a redelivered webhook (Razorpay retries on anything but a 2xx) hits
the unique constraint and is treated as an already-processed no-op,
regardless of what kind of event it is or what side effect it would
otherwise trigger.

`payload` is retained for audit/debugging (§0.11 -- being able to answer
"what did the provider actually send us" without re-requesting it from
Razorpay), not treated as re-parseable business state -- once
`processed_at` is set, the event is done, permanently.
"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from offerleaks.core.db import Base


class WebhookEvent(Base):
    __tablename__ = "webhook_events"
    __table_args__ = (
        UniqueConstraint(
            "provider", "provider_event_id", name="uq_webhook_events_provider_event_id"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    # "razorpay" today; a plain string (not an enum) since a second
    # payment provider is a config/plumbing change, not a schema one --
    # same reasoning as `AnalysisFailureReason`.
    provider: Mapped[str] = mapped_column(String(50), nullable=False)
    # The provider's own event id (Razorpay's `event.id` / the
    # `x-razorpay-event-id`-equivalent field in the payload) -- the only
    # thing a redelivered webhook can be trusted to be identified by.
    provider_event_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)

    payload: Mapped[dict[str, object]] = mapped_column(JSON, nullable=False)

    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
