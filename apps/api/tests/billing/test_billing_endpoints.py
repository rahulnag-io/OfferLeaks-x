"""Integration tests for `/billing/*` against the real app, DB, and Redis
-- same convention as `tests/analyses/test_analyses_endpoints.py`, with
the Razorpay boundary faked via `app.dependency_overrides`.
"""

import json

from offerleaks.core.db import async_session_factory
from offerleaks.models.plan import PRO_PLAN_KEY
from offerleaks.providers.factory import get_payment_provider
from offerleaks.repositories.plan_repository import PlanRepository

from .fakes import FakePaymentProvider, build_subscription_webhook_payload, sign_payload

REGISTER_BODY = {
    "email": "alice@example.com",
    "password": "correcthorsebattery",
    "full_name": "Alice",
}


def _install_fake_payment_provider(app) -> FakePaymentProvider:
    payments = FakePaymentProvider()
    app.dependency_overrides[get_payment_provider] = lambda: payments
    return payments


async def _register_and_get_token(client) -> str:
    response = await client.post("/auth/register", json=REGISTER_BODY)
    return response.json()["access_token"]


async def test_list_plans_is_public_and_includes_free_and_pro(app, client):
    _install_fake_payment_provider(app)

    response = await client.get("/billing/plans")

    assert response.status_code == 200
    keys = {plan["key"] for plan in response.json()}
    assert {"free", "pro"} <= keys


async def test_get_my_entitlements_requires_authentication(app, client):
    _install_fake_payment_provider(app)
    response = await client.get("/billing/me")
    assert response.status_code == 401


async def test_get_my_entitlements_defaults_to_free_plan(app, client):
    _install_fake_payment_provider(app)
    token = await _register_and_get_token(client)

    response = await client.get(
        "/billing/me", headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["plan"]["key"] == "free"
    assert body["subscription_status"] is None
    assert body["monthly_analyses_used"] == 0


async def test_subscribe_without_razorpay_plan_id_returns_400(app, client):
    _install_fake_payment_provider(app)
    token = await _register_and_get_token(client)

    response = await client.post(
        "/billing/subscribe",
        headers={"Authorization": f"Bearer {token}"},
        json={"plan_key": PRO_PLAN_KEY},
    )

    # Pro's razorpay_plan_id is unset until the manual dashboard setup
    # step (see BILLING.md) -- this is the documented, expected failure
    # mode until an operator finishes that step, not a bug.
    assert response.status_code == 400


async def test_subscribe_response_includes_razorpay_subscription_id_and_key(app, client):
    """Regression test: the frontend needs Razorpay's own subscription id
    and the publishable key id to launch Checkout.js -- a response
    missing either field means checkout can never be authenticated,
    even though subscription creation itself succeeded (see BILLING
    incident: 'Hosted page is not available')."""
    _install_fake_payment_provider(app)
    token = await _register_and_get_token(client)

    async with async_session_factory() as db:
        plan = await PlanRepository(db).get_by_key(PRO_PLAN_KEY)
        assert plan is not None
        plan.razorpay_plan_id = "plan_fake_pro"
        await db.commit()

    response = await client.post(
        "/billing/subscribe",
        headers={"Authorization": f"Bearer {token}"},
        json={"plan_key": PRO_PLAN_KEY},
    )

    assert response.status_code == 201
    body = response.json()
    assert body["razorpay_subscription_id"].startswith("sub_")
    assert body["razorpay_key_id"] != ""


async def test_cancel_without_a_subscription_returns_404(app, client):
    _install_fake_payment_provider(app)
    token = await _register_and_get_token(client)

    response = await client.post(
        "/billing/cancel", headers={"Authorization": f"Bearer {token}"}
    )
    assert response.status_code == 404


async def test_webhook_rejects_missing_signature(app, client):
    _install_fake_payment_provider(app)
    payload = build_subscription_webhook_payload(
        event="subscription.activated", razorpay_subscription_id="sub_x"
    )

    response = await client.post(
        "/billing/webhooks/razorpay", content=json.dumps(payload)
    )
    assert response.status_code == 401


async def test_webhook_rejects_invalid_signature(app, client):
    _install_fake_payment_provider(app)
    payload = build_subscription_webhook_payload(
        event="subscription.activated", razorpay_subscription_id="sub_x"
    )

    response = await client.post(
        "/billing/webhooks/razorpay",
        content=json.dumps(payload),
        headers={"X-Razorpay-Signature": "not-the-real-signature"},
    )
    assert response.status_code == 401


async def test_webhook_accepts_a_correctly_signed_unknown_subscription_event(app, client):
    """A validly-signed webhook for a subscription we have no record of
    (e.g. a test event from the Razorpay dashboard) must still return 2xx
    -- see `BillingService._apply_event`'s docstring on why raising here
    would be wrong."""
    _install_fake_payment_provider(app)
    payload = build_subscription_webhook_payload(
        event="subscription.activated", razorpay_subscription_id="sub_never_created"
    )
    raw = json.dumps(payload).encode("utf-8")

    response = await client.post(
        "/billing/webhooks/razorpay",
        content=raw,
        headers={"X-Razorpay-Signature": sign_payload(raw)},
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}
