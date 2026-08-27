"""Billing business logic (M6: Trust Verdict + Monetization Foundation).

Owns the full subscription lifecycle -- create, cancel, and every webhook
event Razorpay sends about it -- the same way `AnalysisService` owns the
upload/OCR/AI lifecycle and `CreditService` owns balance mutations.
Routers call only this; `PaymentProvider`, `SubscriptionRepository`,
`WebhookRepository`, `UsageLedgerRepository`, and `CreditService` are all
private collaborators, never imported directly by `api/routers/billing.py`.

Idempotency, end to end (three independent layers, each guarding a
different replay scenario):

1. `WebhookRepository` -- guards against Razorpay redelivering the exact
   same event (their own retry-on-non-2xx behavior). A duplicate event
   is detected before any business logic runs and is a silent no-op.
2. `UsageLedgerRepository` -- guards against granting the *same billing
   period's* credits twice, even from two different event types that
   both imply "this period was paid for" (e.g. `subscription.charged`
   and `subscription.activated` firing close together).
3. `CreditRepository`'s existing unique-ledger-per-analysis constraint
   (Version 4, unchanged) -- irrelevant to subscription grants
   (`analysis_id` is always `None` here) but still the mechanism that
   makes the resulting `CreditTransaction` audit trail trustworthy.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.plan import Plan
from offerleaks.models.subscription import Subscription, SubscriptionStatus
from offerleaks.models.user import User
from offerleaks.providers.payment import (
    PaymentPermanentError,
    PaymentProvider,
    WebhookEventData,
)
from offerleaks.repositories.plan_repository import PlanRepository
from offerleaks.repositories.subscription_repository import SubscriptionRepository
from offerleaks.repositories.usage_ledger_repository import UsageLedgerRepository
from offerleaks.repositories.webhook_repository import WebhookRepository
from offerleaks.services.credit_service import CreditService

logger = logging.getLogger(__name__)


class BillingServiceError(Exception):
    """Base class for all billing-service failures. Routers map this to 4xx."""


class PlanNotSubscribableError(BillingServiceError):
    """Raised for the free plan (nothing to subscribe to) or a plan with
    no `razorpay_plan_id` configured yet -- see `Plan.razorpay_plan_id`'s
    docstring; this is expected until the manual Razorpay dashboard setup
    is done, not a bug."""


class AlreadySubscribedError(BillingServiceError):
    """`user_id` already has an active (or past_due) subscription. Handle
    plan changes as cancel-then-resubscribe in v1 -- true upgrade/downgrade
    proration is explicitly out of M6's scope (Revised_ARCHITECTURE.md
    lists this under later milestones)."""


class SubscriptionNotFoundError(BillingServiceError):
    pass


@dataclass(frozen=True, slots=True)
class SubscriptionCheckout:
    subscription_id: uuid.UUID
    razorpay_subscription_id: str
    # Razorpay's "Subscription Link" -- kept for reference/fallback only.
    # The primary checkout path is client-side Checkout.js using
    # `razorpay_subscription_id`, not a redirect to this URL (see
    # RazorpayProvider.create_subscription's docstring on why).
    checkout_url: str | None


# Razorpay subscription webhook event types this service reacts to.
# Anything else is still recorded (for audit, via `WebhookRepository`)
# but produces no side effect -- an unrecognized-but-harmless event
# should never be treated as an error (Razorpay adds new event types
# over time; a 4xx/5xx response to one just makes Razorpay keep retrying
# forever for no reason).
_EVENT_ACTIVATED = "subscription.activated"
_EVENT_CHARGED = "subscription.charged"
_EVENT_CANCELLED = "subscription.cancelled"
_EVENT_COMPLETED = "subscription.completed"
_EVENT_HALTED = "subscription.halted"
_EVENT_PENDING = "subscription.pending"  # renewal charge failed, will retry


class BillingService:
    def __init__(self, db: AsyncSession, payment_provider: PaymentProvider) -> None:
        self._db = db
        self._payments = payment_provider
        self._plans = PlanRepository(db)
        self._subscriptions = SubscriptionRepository(db)
        self._webhooks = WebhookRepository(db)
        self._usage_ledger = UsageLedgerRepository(db)
        self._credits = CreditService(db)

    async def list_plans(self) -> list[Plan]:
        return await self._plans.list_active()

    async def get_current_subscription(self, user_id: uuid.UUID) -> Subscription | None:
        return await self._subscriptions.get_by_user_id(user_id)

    async def create_subscription(self, *, user: User, plan_key: str) -> SubscriptionCheckout:
        """Starts a new subscription for `user` to the plan identified by
        `plan_key`. Returns a Razorpay-hosted checkout URL for the client
        to redirect the user to -- this service never collects or
        touches card details itself (§0.11: sensitive payment data never
        passes through our own servers).
        """
        plan = await self._plans.get_by_key(plan_key)
        if plan is None or plan.razorpay_plan_id is None:
            raise PlanNotSubscribableError(plan_key)

        existing = await self._subscriptions.get_by_user_id(user.id)
        if existing is not None and existing.status in (
            SubscriptionStatus.ACTIVE,
            SubscriptionStatus.PAST_DUE,
        ):
            raise AlreadySubscribedError(str(existing.id))

        customer_id = await self._payments.create_customer(
            email=user.email, name=user.full_name or user.email
        )
        provider_subscription = await self._payments.create_subscription(
            provider_plan_id=plan.razorpay_plan_id, customer_id=customer_id
        )

        if existing is not None:
            # A prior CREATED/CANCELED/EXPIRED subscription row for this
            # user -- reuse the row (still unique on `user_id`) rather
            # than leaving an orphaned historical one behind.
            existing.plan_id = plan.id
            existing.razorpay_subscription_id = provider_subscription.provider_subscription_id
            existing.razorpay_customer_id = customer_id
            existing.status = SubscriptionStatus.CREATED
            existing.cancel_at_period_end = False
            await self._db.flush()
            subscription = existing
        else:
            subscription = await self._subscriptions.create(
                user_id=user.id,
                plan_id=plan.id,
                razorpay_subscription_id=provider_subscription.provider_subscription_id,
                razorpay_customer_id=customer_id,
                status=SubscriptionStatus.CREATED,
            )
        await self._db.commit()

        return SubscriptionCheckout(
            subscription_id=subscription.id,
            razorpay_subscription_id=provider_subscription.provider_subscription_id,
            checkout_url=provider_subscription.short_url,
        )

    async def cancel_subscription(self, *, user: User) -> Subscription:
        """Cancels `user`'s subscription at the end of the current
        billing period (`cancel_at_period_end=True`) -- the user keeps
        Pro entitlements through what they already paid for; the actual
        downgrade to Free happens when the `subscription.cancelled`
        webhook confirms the period has ended, not immediately here.
        """
        subscription = await self._subscriptions.get_by_user_id(user.id)
        if subscription is None or subscription.razorpay_subscription_id is None:
            raise SubscriptionNotFoundError

        await self._payments.cancel_subscription(
            provider_subscription_id=subscription.razorpay_subscription_id,
            cancel_at_period_end=True,
        )
        updated = await self._subscriptions.update_status(
            subscription, status=subscription.status, cancel_at_period_end=True
        )
        await self._db.commit()
        return updated

    async def handle_webhook(self, *, event: WebhookEventData) -> None:
        """Processes one already-signature-verified Razorpay webhook
        event. Idempotent: a redelivered event (same `provider_event_id`)
        is detected by `WebhookRepository.record_once` and this method
        returns immediately without redoing any side effect (see module
        docstring for the full idempotency layering).
        """
        recorded = await self._webhooks.record_once(
            provider="razorpay",
            provider_event_id=event.provider_event_id,
            event_type=event.event_type,
            payload=event.payload,
        )
        if recorded is None:
            logger.info("razorpay webhook %s already processed, skipping", event.provider_event_id)
            await self._db.commit()
            return

        try:
            await self._apply_event(event)
        except Exception:
            # The WebhookEvent row itself still commits (recording that we
            # *saw* this event, even if applying it failed) -- but without
            # `processed_at` set, so it's visible in `webhook_events` as
            # "received but not successfully applied" for manual
            # investigation, rather than silently lost. Re-raise so the
            # router returns a 5xx and Razorpay retries the delivery;
            # `record_once`'s guard means a retry-triggered reprocessing
            # of the *business logic* only happens if this handler
            # failed before commit, never a duplicate side effect for an
            # event that already succeeded.
            await self._db.commit()
            raise

        await self._webhooks.mark_processed(recorded, processed_at=datetime.now(UTC))
        await self._db.commit()

    async def _apply_event(self, event: WebhookEventData) -> None:
        entity = event.payload.get("payload", {}).get("subscription", {}).get("entity")
        if not isinstance(entity, dict):
            logger.info(
                "razorpay webhook %s (%s) has no subscription entity, ignoring",
                event.provider_event_id,
                event.event_type,
            )
            return

        provider_subscription_id = entity.get("id")
        if not provider_subscription_id:
            return

        subscription = await self._subscriptions.get_by_razorpay_subscription_id(
            provider_subscription_id
        )
        if subscription is None:
            # A webhook for a subscription we don't have a row for --
            # most likely a test event, or a subscription created
            # directly in the Razorpay dashboard rather than through
            # `create_subscription`. Nothing to update; log and move on
            # rather than raising, since raising here would just cause
            # Razorpay to retry forever for a webhook we can never act on.
            logger.warning(
                "razorpay webhook for unknown subscription %s, ignoring",
                provider_subscription_id,
            )
            return

        current_period_start = _parse_epoch(entity.get("current_start"))
        current_period_end = _parse_epoch(entity.get("current_end"))

        if event.event_type in (_EVENT_ACTIVATED, _EVENT_CHARGED):
            await self._subscriptions.update_status(
                subscription,
                status=SubscriptionStatus.ACTIVE,
                current_period_start=current_period_start,
                current_period_end=current_period_end,
            )
            await self._grant_period_credits(subscription, entity)
        elif event.event_type == _EVENT_PENDING:
            await self._subscriptions.update_status(
                subscription, status=SubscriptionStatus.PAST_DUE
            )
        elif event.event_type in (_EVENT_CANCELLED, _EVENT_COMPLETED, _EVENT_HALTED):
            await self._subscriptions.update_status(
                subscription, status=SubscriptionStatus.CANCELED
            )
        else:
            logger.info("razorpay webhook event type %s has no handler, ignoring", event.event_type)

    async def _grant_period_credits(self, subscription: Subscription, entity: dict) -> None:
        plan = await self._plans.get_by_id(subscription.plan_id)
        if plan is None or plan.monthly_credit_grant <= 0:
            return

        # Prefer Razorpay's own cycle counter for the idempotency key
        # (stable, monotonic, present on every charge/activation event);
        # fall back to the period-start timestamp if it's ever absent so
        # a grant still only fires once per distinct period either way.
        period_key = str(
            entity.get("paid_count")
            or entity.get("current_start")
            or subscription.current_period_start
        )

        ledger_entry = await self._usage_ledger.record_grant_once(
            user_id=subscription.user_id,
            subscription_id=subscription.id,
            period_key=period_key,
            credits_granted=plan.monthly_credit_grant,
        )
        if ledger_entry is None:
            # Already granted for this period (e.g. `activated` and
            # `charged` both fired for the same first cycle) -- no-op.
            return

        await self._credits.grant_subscription_credits(
            user_id=subscription.user_id, amount=plan.monthly_credit_grant
        )


def _parse_epoch(value: object) -> datetime | None:
    if not isinstance(value, int | float):
        return None
    return datetime.fromtimestamp(value, tz=UTC)


__all__ = [
    "AlreadySubscribedError",
    "BillingService",
    "BillingServiceError",
    "PaymentPermanentError",
    "PlanNotSubscribableError",
    "SubscriptionCheckout",
    "SubscriptionNotFoundError",
]
