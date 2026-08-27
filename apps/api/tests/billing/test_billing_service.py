"""Tests for `offerleaks.services.billing_service.BillingService` (M6).

Runs against real Postgres (subscriptions, webhook_events, usage_ledger,
credit_balances) with `PaymentProvider` faked -- the same reasoning as
every other provider-backed test module in this suite: this is exactly
the seam the interface exists to isolate, and hitting a real Razorpay
account from an automated test run isn't possible or desirable.
"""

import json
import uuid

from offerleaks.core.db import async_session_factory
from offerleaks.models.plan import PRO_PLAN_KEY
from offerleaks.models.subscription import SubscriptionStatus
from offerleaks.models.user import User
from offerleaks.repositories.plan_repository import PlanRepository
from offerleaks.repositories.subscription_repository import SubscriptionRepository
from offerleaks.services.billing_service import (
    AlreadySubscribedError,
    BillingService,
    PlanNotSubscribableError,
    SubscriptionNotFoundError,
)
from offerleaks.services.credit_service import CreditService

from .fakes import FakePaymentProvider, build_subscription_webhook_payload


async def _create_user() -> User:
    async with async_session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
        db.add(user)
        await db.flush()
        credits = CreditService(db)
        await credits.grant_initial_credits(user.id)
        await db.commit()
        await db.refresh(user)
        return user


async def _set_pro_plan_razorpay_id(razorpay_plan_id: str = "plan_fake_pro") -> None:
    """The seed migration leaves `Plan.razorpay_plan_id` unset for Pro
    (see that migration's docstring) -- tests that need a subscribable
    plan fill it in directly, mirroring the manual dashboard-setup step
    real operators perform."""
    async with async_session_factory() as db:
        plan = await PlanRepository(db).get_by_key(PRO_PLAN_KEY)
        assert plan is not None
        plan.razorpay_plan_id = razorpay_plan_id
        await db.commit()


async def test_create_subscription_fails_if_plan_not_subscribable():
    user = await _create_user()
    payments = FakePaymentProvider()

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        try:
            await billing.create_subscription(user=user, plan_key=PRO_PLAN_KEY)
            raised = False
        except PlanNotSubscribableError:
            raised = True
    # Pro's razorpay_plan_id is unset until the manual dashboard step --
    # see `_set_pro_plan_razorpay_id`.
    assert raised


async def test_create_subscription_happy_path_creates_a_subscription_row():
    await _set_pro_plan_razorpay_id()
    user = await _create_user()
    payments = FakePaymentProvider()

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        checkout = await billing.create_subscription(user=user, plan_key=PRO_PLAN_KEY)

    assert checkout.razorpay_subscription_id is not None
    assert payments.created_customers == [(user.email, user.full_name or user.email)]
    assert len(payments.created_subscriptions) == 1

    async with async_session_factory() as db:
        subscription = await SubscriptionRepository(db).get_by_user_id(user.id)
    assert subscription is not None
    assert subscription.status == SubscriptionStatus.CREATED
    assert subscription.razorpay_subscription_id is not None


async def test_create_subscription_rejects_a_second_active_subscription():
    await _set_pro_plan_razorpay_id()
    user = await _create_user()
    payments = FakePaymentProvider()

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        checkout = await billing.create_subscription(user=user, plan_key=PRO_PLAN_KEY)

    # Simulate the subscription having actually activated (a real user
    # would get here via the `subscription.activated` webhook).
    async with async_session_factory() as db:
        subs_repo = SubscriptionRepository(db)
        subscription = await subs_repo.get_by_user_id(user.id)
        assert subscription is not None
        await subs_repo.update_status(subscription, status=SubscriptionStatus.ACTIVE)
        await db.commit()

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        try:
            await billing.create_subscription(user=user, plan_key=PRO_PLAN_KEY)
            raised = False
        except AlreadySubscribedError:
            raised = True
    assert raised
    assert checkout.subscription_id is not None


async def test_cancel_subscription_without_one_raises_not_found():
    user = await _create_user()
    payments = FakePaymentProvider()

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        try:
            await billing.cancel_subscription(user=user)
            raised = False
        except SubscriptionNotFoundError:
            raised = True
    assert raised


async def test_cancel_subscription_sets_cancel_at_period_end():
    await _set_pro_plan_razorpay_id()
    user = await _create_user()
    payments = FakePaymentProvider()

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        await billing.create_subscription(user=user, plan_key=PRO_PLAN_KEY)

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        subscription = await billing.cancel_subscription(user=user)

    assert subscription.cancel_at_period_end is True
    assert len(payments.cancelled_subscriptions) == 1
    assert payments.cancelled_subscriptions[0][1] is True  # cancel_at_period_end


async def test_webhook_activation_grants_period_credits_once():
    await _set_pro_plan_razorpay_id()
    user = await _create_user()
    payments = FakePaymentProvider()

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        await billing.create_subscription(user=user, plan_key=PRO_PLAN_KEY)
        subscription = await SubscriptionRepository(db).get_by_user_id(user.id)
    assert subscription is not None

    payload = build_subscription_webhook_payload(
        event="subscription.activated",
        razorpay_subscription_id=subscription.razorpay_subscription_id,
    )
    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        event = payments.parse_webhook_event(payload=json.dumps(payload).encode("utf-8"))
        await billing.handle_webhook(event=event)

    async with async_session_factory() as db:
        credits = CreditService(db)
        balance = await credits.get_balance(user.id)
        subscription = await SubscriptionRepository(db).get_by_user_id(user.id)

    assert subscription is not None
    assert subscription.status == SubscriptionStatus.ACTIVE
    # Initial signup grant (3, config default) + Pro's monthly grant (50,
    # seed migration) = 53.
    assert balance == 53


async def test_duplicate_webhook_event_does_not_grant_credits_twice():
    """The core idempotency guarantee this whole feature exists for --
    see `BillingService`'s module docstring."""
    await _set_pro_plan_razorpay_id()
    user = await _create_user()
    payments = FakePaymentProvider()

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        await billing.create_subscription(user=user, plan_key=PRO_PLAN_KEY)
        subscription = await SubscriptionRepository(db).get_by_user_id(user.id)
    assert subscription is not None

    payload = build_subscription_webhook_payload(
        event="subscription.activated",
        razorpay_subscription_id=subscription.razorpay_subscription_id,
    )
    raw = json.dumps(payload).encode("utf-8")

    for _ in range(3):
        async with async_session_factory() as db:
            billing = BillingService(db, payments)
            event = payments.parse_webhook_event(payload=raw)
            await billing.handle_webhook(event=event)

    async with async_session_factory() as db:
        credits = CreditService(db)
        balance = await credits.get_balance(user.id)

    # Not 3x53=159 or even 3+50*3 -- exactly one grant applied, no matter
    # how many times the identical webhook was redelivered.
    assert balance == 53


async def test_different_billing_periods_each_grant_once():
    """Two genuinely different renewal events for the same subscription
    (different `paid_count`/period) should each grant once -- the guard
    is per-period, not "ever, for this subscription."""
    await _set_pro_plan_razorpay_id()
    user = await _create_user()
    payments = FakePaymentProvider()

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        await billing.create_subscription(user=user, plan_key=PRO_PLAN_KEY)
        subscription = await SubscriptionRepository(db).get_by_user_id(user.id)
    assert subscription is not None

    for cycle in (1, 2):
        payload = build_subscription_webhook_payload(
            event="subscription.charged",
            razorpay_subscription_id=subscription.razorpay_subscription_id,
            paid_count=cycle,
            created_at=1_700_000_000 + cycle,
        )
        async with async_session_factory() as db:
            billing = BillingService(db, payments)
            event = payments.parse_webhook_event(payload=json.dumps(payload).encode("utf-8"))
            await billing.handle_webhook(event=event)

    async with async_session_factory() as db:
        credits = CreditService(db)
        balance = await credits.get_balance(user.id)

    # 3 (signup) + 50 (cycle 1) + 50 (cycle 2) = 103.
    assert balance == 103


async def test_webhook_for_unknown_subscription_is_ignored_not_errored():
    payments = FakePaymentProvider()
    payload = build_subscription_webhook_payload(
        event="subscription.activated", razorpay_subscription_id="sub_does_not_exist"
    )
    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        event = payments.parse_webhook_event(payload=json.dumps(payload).encode("utf-8"))
        # Must not raise.
        await billing.handle_webhook(event=event)


async def test_cancellation_webhook_marks_subscription_canceled():
    await _set_pro_plan_razorpay_id()
    user = await _create_user()
    payments = FakePaymentProvider()

    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        await billing.create_subscription(user=user, plan_key=PRO_PLAN_KEY)
        subscription = await SubscriptionRepository(db).get_by_user_id(user.id)
    assert subscription is not None

    payload = build_subscription_webhook_payload(
        event="subscription.cancelled",
        razorpay_subscription_id=subscription.razorpay_subscription_id,
    )
    async with async_session_factory() as db:
        billing = BillingService(db, payments)
        event = payments.parse_webhook_event(payload=json.dumps(payload).encode("utf-8"))
        await billing.handle_webhook(event=event)

    async with async_session_factory() as db:
        subscription = await SubscriptionRepository(db).get_by_user_id(user.id)
    assert subscription is not None
    assert subscription.status == SubscriptionStatus.CANCELED
