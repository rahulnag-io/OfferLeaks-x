"""Data access for `Subscription`.

Every write here is scoped to a single row (one subscription per user --
`uq_subscriptions_user_id`), so unlike `CreditRepository`'s conditional
`UPDATE ... RETURNING` pattern, ordinary `UPDATE ... WHERE id = ...` is
sufficient: there's no "two concurrent requests racing to decrement a
shared counter" shape here. The concurrency concern for billing is
webhook *replay*, not concurrent mutation of the same row -- that's
guarded by `WebhookRepository`, one layer up.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.subscription import Subscription, SubscriptionStatus


class SubscriptionRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_user_id(self, user_id: uuid.UUID) -> Subscription | None:
        result = await self._db.execute(
            select(Subscription).where(Subscription.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def get_by_razorpay_subscription_id(
        self, razorpay_subscription_id: str
    ) -> Subscription | None:
        result = await self._db.execute(
            select(Subscription).where(
                Subscription.razorpay_subscription_id == razorpay_subscription_id
            )
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        plan_id: uuid.UUID,
        razorpay_subscription_id: str | None,
        razorpay_customer_id: str | None,
        status: SubscriptionStatus = SubscriptionStatus.CREATED,
    ) -> Subscription:
        subscription = Subscription(
            user_id=user_id,
            plan_id=plan_id,
            razorpay_subscription_id=razorpay_subscription_id,
            razorpay_customer_id=razorpay_customer_id,
            status=status,
        )
        self._db.add(subscription)
        await self._db.flush()
        return subscription

    async def update_status(
        self,
        subscription: Subscription,
        *,
        status: SubscriptionStatus,
        current_period_start: datetime | None = None,
        current_period_end: datetime | None = None,
        cancel_at_period_end: bool | None = None,
    ) -> Subscription:
        subscription.status = status
        if current_period_start is not None:
            subscription.current_period_start = current_period_start
        if current_period_end is not None:
            subscription.current_period_end = current_period_end
        if cancel_at_period_end is not None:
            subscription.cancel_at_period_end = cancel_at_period_end
        await self._db.flush()
        return subscription
