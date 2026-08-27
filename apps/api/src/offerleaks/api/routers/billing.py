"""Billing endpoints (M6: Trust Verdict + Monetization Foundation).

Routers stay thin (architecture.md §0.3) -- all business logic lives in
`BillingService`/`EntitlementService`. The one endpoint here that looks
unusual next to the rest of the API is the webhook: it has no
`CurrentUser` dependency (Razorpay is the caller, not a logged-in user)
and reads the *raw* request body before any parsing, because signature
verification (`PaymentProvider.verify_webhook_signature`) must run
against the exact bytes Razorpay signed.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.auth.dependencies import CurrentUser
from offerleaks.core.config import Settings, get_settings
from offerleaks.core.db import get_db_session
from offerleaks.core.rate_limit import rate_limit
from offerleaks.providers.factory import get_payment_provider
from offerleaks.providers.payment import (
    PaymentPermanentError,
    PaymentProvider,
    WebhookSignatureError,
)
from offerleaks.schemas.billing import (
    CreateSubscriptionRequest,
    CreateSubscriptionResponse,
    EntitlementsResponse,
    PlanResponse,
)
from offerleaks.services.billing_service import (
    AlreadySubscribedError,
    BillingService,
    PlanNotSubscribableError,
    SubscriptionNotFoundError,
)
from offerleaks.services.entitlement_service import EntitlementService

router = APIRouter(prefix="/billing", tags=["billing"])

# Webhooks are unauthenticated by nature (Razorpay, not a logged-in user,
# calls this) but still rate-limited per-IP -- the same posture as the
# Version 2 login endpoint before an authenticated caller exists.
_webhook_rate_limit = rate_limit(key="billing_webhook", max_attempts=60, window_seconds=60)


def _get_billing_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
    payment_provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
) -> BillingService:
    return BillingService(db, payment_provider)


def _get_entitlement_service(
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> EntitlementService:
    return EntitlementService(db)


@router.get("/plans", response_model=list[PlanResponse])
async def list_plans(
    billing_service: Annotated[BillingService, Depends(_get_billing_service)],
) -> list[PlanResponse]:
    plans = await billing_service.list_plans()
    return [PlanResponse.model_validate(plan) for plan in plans]


@router.get("/me", response_model=EntitlementsResponse)
async def get_my_entitlements(
    current_user: CurrentUser,
    entitlements: Annotated[EntitlementService, Depends(_get_entitlement_service)],
) -> EntitlementsResponse:
    resolution = await entitlements.resolve_plan(current_user.id)
    used = await entitlements.monthly_analysis_count(current_user.id)

    return EntitlementsResponse(
        plan=PlanResponse.model_validate(resolution.plan),
        subscription_status=resolution.subscription.status if resolution.subscription else None,
        cancel_at_period_end=(
            resolution.subscription.cancel_at_period_end if resolution.subscription else False
        ),
        current_period_end=(
            resolution.subscription.current_period_end if resolution.subscription else None
        ),
        monthly_analyses_used=used,
        monthly_analysis_limit=resolution.plan.monthly_analysis_limit,
    )


@router.post(
    "/subscribe",
    response_model=CreateSubscriptionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_subscription(
    body: CreateSubscriptionRequest,
    current_user: CurrentUser,
    billing_service: Annotated[BillingService, Depends(_get_billing_service)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> CreateSubscriptionResponse:
    try:
        checkout = await billing_service.create_subscription(
            user=current_user, plan_key=body.plan_key
        )
    except PlanNotSubscribableError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=(
                "This plan isn't available for checkout yet. If you're the "
                "site operator, see BILLING.md to finish the Razorpay setup."
            ),
        ) from exc
    except AlreadySubscribedError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="You already have an active subscription.",
        ) from exc
    except PaymentPermanentError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="We couldn't start checkout with our payment provider. Please try again.",
        ) from exc

    return CreateSubscriptionResponse(
        subscription_id=checkout.subscription_id,
        razorpay_subscription_id=checkout.razorpay_subscription_id,
        # RAZORPAY_KEY_ID is Razorpay's publishable key -- the same value
        # Checkout.js always requires client-side, not the API secret
        # (RAZORPAY_KEY_SECRET). Safe to return in an authenticated
        # response body.
        razorpay_key_id=settings.razorpay_key_id,
        checkout_url=checkout.checkout_url,
    )


@router.post("/cancel", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_subscription(
    current_user: CurrentUser,
    billing_service: Annotated[BillingService, Depends(_get_billing_service)],
) -> None:
    try:
        await billing_service.cancel_subscription(user=current_user)
    except SubscriptionNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="You don't have an active subscription to cancel.",
        ) from exc
    except PaymentPermanentError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="We couldn't reach our payment provider to cancel this subscription.",
        ) from exc


@router.post("/webhooks/razorpay", status_code=status.HTTP_200_OK)
async def razorpay_webhook(
    request: Request,
    billing_service: Annotated[BillingService, Depends(_get_billing_service)],
    payment_provider: Annotated[PaymentProvider, Depends(get_payment_provider)],
    _: Annotated[None, Depends(_webhook_rate_limit)],
) -> dict[str, bool]:
    """Razorpay's webhook target (Dashboard -> Settings -> Webhooks). See
    BILLING.md for the exact URL/secret/event-selection to configure
    there.

    Always returns 2xx once the signature is valid, *regardless* of
    whether the event type is one this system reacts to -- Razorpay
    retries on anything but 2xx, and there is no reason to make it retry
    an event we're deliberately ignoring (see `BillingService._apply_event`).
    A 4xx/5xx here should only ever mean "this wasn't a genuine,
    correctly-signed Razorpay request" or "we hit an unexpected error and
    do want Razorpay to retry."
    """
    raw_body = await request.body()
    signature = request.headers.get("X-Razorpay-Signature")
    if not signature or not payment_provider.verify_webhook_signature(
        payload=raw_body, signature=signature
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid webhook signature"
        )

    try:
        event = payment_provider.parse_webhook_event(payload=raw_body)
    except PaymentPermanentError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    try:
        await billing_service.handle_webhook(event=event)
    except WebhookSignatureError as exc:  # pragma: no cover - defense in depth
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc

    return {"ok": True}
