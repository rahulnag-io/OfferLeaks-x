"""Request/response DTOs for `api/routers/billing.py` (M6)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from offerleaks.models.subscription import SubscriptionStatus


class PlanResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    key: str
    name: str
    monthly_credit_grant: int
    monthly_analysis_limit: int | None
    price_amount_minor: int
    price_currency: str


class EntitlementsResponse(BaseModel):
    """`GET /billing/me` -- the current user's plan, subscription status,
    and this month's usage against it. This is the one endpoint the
    frontend's plan/usage indicator (dashboard) and pricing page's "your
    current plan" state both read from."""

    plan: PlanResponse
    subscription_status: SubscriptionStatus | None
    cancel_at_period_end: bool
    current_period_end: datetime | None
    monthly_analyses_used: int
    monthly_analysis_limit: int | None


class CreateSubscriptionRequest(BaseModel):
    plan_key: str



class CreateSubscriptionResponse(BaseModel):
    subscription_id: uuid.UUID
    razorpay_subscription_id: str
    razorpay_key_id: str
    checkout_url: str | None
