"""Tests for `offerleaks.services.entitlement_service.EntitlementService`
(M6). Runs against real Postgres, same convention as `test_credit_service.py`.
"""

import uuid
from datetime import UTC, datetime

from offerleaks.core.db import async_session_factory
from offerleaks.models.plan import FREE_PLAN_KEY, PRO_PLAN_KEY
from offerleaks.models.subscription import Subscription, SubscriptionStatus
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.plan_repository import PlanRepository
from offerleaks.services.entitlement_service import (
    EntitlementService,
    MonthlyAnalysisLimitExceededError,
)


async def _create_user() -> uuid.UUID:
    async with async_session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
        db.add(user)
        await db.flush()
        await db.commit()
        return user.id


async def _create_analysis(user_id: uuid.UUID) -> None:
    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        await repo.create(
            user_id=user_id,
            file_storage_key=f"analyses/{user_id}/{uuid.uuid4()}/offer.pdf",
            file_name="offer.pdf",
            file_mime_type="application/pdf",
            file_size_bytes=100,
            prompt_version="offer_letter_v1",
        )
        await db.commit()


async def _subscribe_to_pro(user_id: uuid.UUID, *, status: SubscriptionStatus) -> None:
    async with async_session_factory() as db:
        plan = await PlanRepository(db).get_by_key(PRO_PLAN_KEY)
        assert plan is not None
        db.add(
            Subscription(
                user_id=user_id,
                plan_id=plan.id,
                razorpay_subscription_id=f"sub_{uuid.uuid4().hex[:10]}",
                status=status,
            )
        )
        await db.commit()


async def test_resolve_plan_defaults_to_free_with_no_subscription():
    user_id = await _create_user()
    async with async_session_factory() as db:
        resolution = await EntitlementService(db).resolve_plan(user_id)

    assert resolution.plan.key == FREE_PLAN_KEY
    assert resolution.subscription is None


async def test_resolve_plan_returns_pro_for_an_active_subscription():
    user_id = await _create_user()
    await _subscribe_to_pro(user_id, status=SubscriptionStatus.ACTIVE)

    async with async_session_factory() as db:
        resolution = await EntitlementService(db).resolve_plan(user_id)

    assert resolution.plan.key == PRO_PLAN_KEY
    assert resolution.subscription is not None


async def test_resolve_plan_still_entitles_past_due_subscriptions():
    """A renewal charge failing shouldn't immediately downgrade the user
    -- see `SubscriptionStatus.PAST_DUE`'s docstring."""
    user_id = await _create_user()
    await _subscribe_to_pro(user_id, status=SubscriptionStatus.PAST_DUE)

    async with async_session_factory() as db:
        resolution = await EntitlementService(db).resolve_plan(user_id)

    assert resolution.plan.key == PRO_PLAN_KEY


async def test_resolve_plan_falls_back_to_free_for_canceled_subscription():
    user_id = await _create_user()
    await _subscribe_to_pro(user_id, status=SubscriptionStatus.CANCELED)

    async with async_session_factory() as db:
        resolution = await EntitlementService(db).resolve_plan(user_id)

    assert resolution.plan.key == FREE_PLAN_KEY


async def test_monthly_analysis_count_only_counts_this_calendar_month():
    user_id = await _create_user()
    await _create_analysis(user_id)
    await _create_analysis(user_id)

    async with async_session_factory() as db:
        count_now = await EntitlementService(db).monthly_analysis_count(user_id)
    assert count_now == 2

    # Analyses "created" far in the future (relative to `now=`) shouldn't
    # be counted against the *current* month's window.
    far_future = datetime(2099, 1, 1, tzinfo=UTC)
    async with async_session_factory() as db:
        count_future_month = await EntitlementService(db).monthly_analysis_count(
            user_id, now=far_future
        )
    assert count_future_month == 0


async def test_assert_within_monthly_quota_passes_for_pro_unlimited():
    user_id = await _create_user()
    await _subscribe_to_pro(user_id, status=SubscriptionStatus.ACTIVE)
    for _ in range(20):
        await _create_analysis(user_id)

    async with async_session_factory() as db:
        # Should not raise -- Pro's monthly_analysis_limit is None.
        await EntitlementService(db).assert_within_monthly_quota(user_id)


async def test_assert_within_monthly_quota_raises_once_free_limit_reached():
    user_id = await _create_user()

    async with async_session_factory() as db:
        entitlements = EntitlementService(db)
        resolution = await entitlements.resolve_plan(user_id)
        limit = resolution.plan.monthly_analysis_limit
    assert limit is not None

    for _ in range(limit):
        await _create_analysis(user_id)

    async with async_session_factory() as db:
        try:
            await EntitlementService(db).assert_within_monthly_quota(user_id)
            raised = False
        except MonthlyAnalysisLimitExceededError as exc:
            raised = True
            assert exc.limit == limit
    assert raised


async def test_assert_within_monthly_quota_passes_below_the_limit():
    user_id = await _create_user()
    await _create_analysis(user_id)

    async with async_session_factory() as db:
        # Should not raise -- well below the free plan's seeded limit (10).
        await EntitlementService(db).assert_within_monthly_quota(user_id)
