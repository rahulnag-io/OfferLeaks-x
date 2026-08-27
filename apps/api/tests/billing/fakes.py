"""Fake `PaymentProvider` for the billing test suite (M6) -- mirrors
`tests/analyses/fakes.py`'s reasoning for the AI/OCR/storage/malware-scan
fakes: no real Razorpay account is reachable or safe to hit from an
automated test run, and `BillingService` only ever knows it's talking to
whatever satisfies the `PaymentProvider` protocol.
"""

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from typing import Any

from offerleaks.providers.payment import (
    PaymentPermanentError,
    ProviderSubscription,
    WebhookEventData,
)

FAKE_WEBHOOK_SECRET = "test-webhook-secret"


@dataclass
class FakePaymentProvider:
    """Records every call it receives so tests can assert on them, and
    lets a test force the next `create_subscription`/`create_customer`
    call to raise, to exercise `BillingService`'s error-mapping paths.
    """

    fail_next_call: bool = False
    created_customers: list[tuple[str, str]] = field(default_factory=list)
    created_subscriptions: list[tuple[str, str]] = field(default_factory=list)
    cancelled_subscriptions: list[tuple[str, bool]] = field(default_factory=list)

    async def create_customer(self, *, email: str, name: str) -> str:
        if self.fail_next_call:
            raise PaymentPermanentError("simulated Razorpay failure")
        self.created_customers.append((email, name))
        return f"cust_fake_{uuid.uuid4().hex[:12]}"

    async def create_subscription(
        self, *, provider_plan_id: str, customer_id: str
    ) -> ProviderSubscription:
        if self.fail_next_call:
            raise PaymentPermanentError("simulated Razorpay failure")
        self.created_subscriptions.append((provider_plan_id, customer_id))
        sub_id = f"sub_fake_{uuid.uuid4().hex[:12]}"
        return ProviderSubscription(
            provider_subscription_id=sub_id,
            status="created",
            short_url=f"https://rzp.io/i/{sub_id}",
        )

    async def cancel_subscription(
        self, *, provider_subscription_id: str, cancel_at_period_end: bool
    ) -> None:
        if self.fail_next_call:
            raise PaymentPermanentError("simulated Razorpay failure")
        self.cancelled_subscriptions.append((provider_subscription_id, cancel_at_period_end))

    def verify_webhook_signature(self, *, payload: bytes, signature: str) -> bool:
        expected = hmac.new(
            FAKE_WEBHOOK_SECRET.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook_event(self, *, payload: bytes) -> WebhookEventData:
        body = json.loads(payload)
        entity_id = None
        for wrapper in body.get("payload", {}).values():
            entity = wrapper.get("entity") if isinstance(wrapper, dict) else None
            if isinstance(entity, dict) and "id" in entity:
                entity_id = entity["id"]
                break
        return WebhookEventData(
            provider_event_id=f"{body.get('event')}:{entity_id}:{body.get('created_at')}",
            event_type=body["event"],
            payload=body,
        )


def sign_payload(payload: bytes, *, secret: str = FAKE_WEBHOOK_SECRET) -> str:
    return hmac.new(secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()


def build_subscription_webhook_payload(
    *,
    event: str,
    razorpay_subscription_id: str,
    current_start: int = 1_700_000_000,
    current_end: int = 1_702_592_000,
    paid_count: int = 1,
    created_at: int = 1_700_000_100,
) -> dict[str, Any]:
    """Builds a Razorpay-shaped `subscription.*` webhook payload, matching
    the real nesting `payload.subscription.entity` this system's
    `RazorpayProvider.parse_webhook_event`/`BillingService._apply_event`
    both read from.
    """
    return {
        "event": event,
        "created_at": created_at,
        "payload": {
            "subscription": {
                "entity": {
                    "id": razorpay_subscription_id,
                    "status": "active",
                    "current_start": current_start,
                    "current_end": current_end,
                    "paid_count": paid_count,
                }
            }
        },
    }
