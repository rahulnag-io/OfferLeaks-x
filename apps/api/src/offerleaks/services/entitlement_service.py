"""Entitlement resolution & enforcement (M6: Trust Verdict + Monetization
Foundation).

This is the single place that answers "what plan is this user on, and
what does that plan let them do" -- routers and `AnalysisService` ask
this rather than reading `Subscription`/`Plan` rows themselves
(architecture.md §0.3's service-ownership convention, same as
`CreditService` for credits).

Deliberately layered *on top of*, not parallel to, the existing credit
system (Version 4): the credit ledger stays the sole mechanism for
"can/did this specific analysis get paid for" (`CreditService`,
unchanged by M6). `EntitlementService` adds a second, independent gate --
"is this user within their plan's monthly analysis allowance" -- because
that's a distinct business rule (a plan-tier cap, not a balance), not a
re-implementation of credit accounting. Both checks must pass for a
paid-plan user's analysis to proceed; a Free user with a positive credit
balance can still be blocked by the monthly cap, and vice versa.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.plan import Plan
from offerleaks.models.subscription import Subscription, SubscriptionStatus
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.plan_repository import PlanRepository
from offerleaks.repositories.subscription_repository import SubscriptionRepository

# Statuses under which a subscription's plan is actually in effect. A
# CREATED (not-yet-authorized) or CANCELED/EXPIRED subscription does not
# entitle the user to its plan -- PAST_DUE still does (see
# `models/subscription.py::SubscriptionStatus` docstring: tolerate a
# transient renewal failure without an immediate downgrade).
_ENTITLING_STATUSES = frozenset({SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE})


class EntitlementServiceError(Exception):
    """Base class for all entitlement-service failures."""


class MonthlyAnalysisLimitExceededError(EntitlementServiceError):
    def __init__(self, *, limit: int, plan_name: str) -> None:
        super().__init__(
            f"monthly analysis limit ({limit}) reached for plan {plan_name!r}"
        )
        self.limit = limit
        self.plan_name = plan_name


@dataclass(frozen=True, slots=True)
class PlanResolution:
    plan: Plan
    subscription: Subscription | None
    entitlements: dict[str, str]


def _month_start(now: datetime | None = None) -> datetime:
    now = now or datetime.now(UTC)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


class EntitlementService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db
        self._plans = PlanRepository(db)
        self._subscriptions = SubscriptionRepository(db)
        self._analyses = AnalysisRepository(db)

    async def resolve_plan(self, user_id: uuid.UUID) -> PlanResolution:
        """Resolves the plan currently in effect for `user_id`.

        A user with no subscription row, or one that isn't in an
        entitling status (see `_ENTITLING_STATUSES`), falls back to the
        Free plan -- there is no "no plan" state (M6 DoD: every user is
        on some plan, Free by default).
        """
        subscription = await self._subscriptions.get_by_user_id(user_id)
        if subscription is not None and subscription.status in _ENTITLING_STATUSES:
            plan = await self._plans.get_by_id(subscription.plan_id)
            if plan is not None:
                entitlements = await self._plans.get_entitlements(plan.id)
                return PlanResolution(
                    plan=plan, subscription=subscription, entitlements=entitlements
                )

        free_plan = await self._plans.get_free_plan()
        entitlements = await self._plans.get_entitlements(free_plan.id)
        return PlanResolution(
            plan=free_plan, subscription=subscription, entitlements=entitlements
        )

    async def monthly_analysis_count(
        self, user_id: uuid.UUID, *, now: datetime | None = None
    ) -> int:
        return await self._analyses.count_since(user_id, since=_month_start(now))

    async def assert_within_monthly_quota(
        self, user_id: uuid.UUID, *, now: datetime | None = None
    ) -> None:
        """Raises `MonthlyAnalysisLimitExceededError` if `user_id` has
        already reached their plan's `monthly_analysis_limit` for the
        current calendar month. A `None` limit (Pro, by default) means
        unlimited -- no query is even issued in that case.

        This is a fast-path check only, same caveat as
        `AnalysisService.create_analysis`'s pre-check against the credit
        balance: it does not hold a lock, so a razor-thin concurrent race
        at exactly the limit boundary is possible in principle. Unlike
        credits (real money-adjacent exposure, hence the atomic
        `try_consume`), a plan's monthly analysis cap allowing one extra
        analysis in a rare race is a soft product limit, not a
        correctness or financial-integrity issue -- so the same
        atomic-UPDATE treatment isn't justified here.
        """
        resolution = await self.resolve_plan(user_id)
        limit = resolution.plan.monthly_analysis_limit
        if limit is None:
            return

        count = await self.monthly_analysis_count(user_id, now=now)
        if count >= limit:
            raise MonthlyAnalysisLimitExceededError(limit=limit, plan_name=resolution.plan.name)
