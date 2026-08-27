"""Tests for `offerleaks.providers.payment.RazorpayProvider`'s pure,
network-free methods -- signature verification and webhook parsing. The
network-calling methods (`create_customer`, `create_subscription`,
`cancel_subscription`) are exercised indirectly through
`BillingService`'s tests via `FakePaymentProvider`, not here: hitting the
real Razorpay API isn't possible from an automated test run (same
reasoning as every other real-vendor provider in this codebase).
"""

import hashlib
import hmac
import json

import pytest

from offerleaks.core.config import Settings
from offerleaks.providers.payment import PaymentPermanentError, RazorpayProvider

_SECRET = "whsec_test_secret"


@pytest.fixture
def provider() -> RazorpayProvider:
    settings = Settings(
        razorpay_key_id="rzp_test_key",
        razorpay_key_secret="rzp_test_secret",
        razorpay_webhook_secret=_SECRET,
    )
    return RazorpayProvider(settings)


def test_missing_api_credentials_raises_permanent_error():
    settings = Settings(razorpay_key_id="", razorpay_key_secret="")
    with pytest.raises(PaymentPermanentError):
        RazorpayProvider(settings)


def test_verify_webhook_signature_accepts_a_correctly_signed_payload(provider):
    payload = b'{"event": "subscription.activated"}'
    signature = hmac.new(_SECRET.encode(), payload, hashlib.sha256).hexdigest()

    assert provider.verify_webhook_signature(payload=payload, signature=signature) is True


def test_verify_webhook_signature_rejects_a_tampered_payload(provider):
    payload = b'{"event": "subscription.activated"}'
    signature = hmac.new(_SECRET.encode(), payload, hashlib.sha256).hexdigest()

    tampered = b'{"event": "subscription.cancelled"}'
    assert provider.verify_webhook_signature(payload=tampered, signature=signature) is False


def test_verify_webhook_signature_rejects_wrong_secret(provider):
    payload = b'{"event": "subscription.activated"}'
    signature = hmac.new(b"wrong-secret", payload, hashlib.sha256).hexdigest()

    assert provider.verify_webhook_signature(payload=payload, signature=signature) is False


def test_verify_webhook_signature_raises_if_secret_unconfigured():
    settings = Settings(
        razorpay_key_id="rzp_test_key",
        razorpay_key_secret="rzp_test_secret",
        razorpay_webhook_secret="",
    )
    provider = RazorpayProvider(settings)

    with pytest.raises(PaymentPermanentError):
        provider.verify_webhook_signature(payload=b"{}", signature="anything")


def test_parse_webhook_event_extracts_entity_id_and_event_type(provider):
    payload = {
        "event": "subscription.activated",
        "created_at": 1_700_000_000,
        "payload": {"subscription": {"entity": {"id": "sub_abc123", "status": "active"}}},
    }
    raw = json.dumps(payload).encode("utf-8")

    event = provider.parse_webhook_event(payload=raw)

    assert event.event_type == "subscription.activated"
    assert "sub_abc123" in event.provider_event_id
    assert event.payload == payload


def test_parse_webhook_event_same_payload_produces_the_same_id(provider):
    """The idempotency key must be deterministic -- re-parsing an
    identical redelivered payload has to produce the same
    `provider_event_id` every time, or `WebhookRepository`'s unique
    constraint can't catch the replay."""
    payload = {
        "event": "subscription.charged",
        "created_at": 1_700_000_555,
        "payload": {"subscription": {"entity": {"id": "sub_xyz", "status": "active"}}},
    }
    raw = json.dumps(payload).encode("utf-8")

    first = provider.parse_webhook_event(payload=raw)
    second = provider.parse_webhook_event(payload=raw)

    assert first.provider_event_id == second.provider_event_id


def test_parse_webhook_event_different_payloads_produce_different_ids(provider):
    payload_a = {
        "event": "subscription.charged",
        "created_at": 1,
        "payload": {"subscription": {"entity": {"id": "sub_a"}}},
    }
    payload_b = {
        "event": "subscription.charged",
        "created_at": 2,
        "payload": {"subscription": {"entity": {"id": "sub_b"}}},
    }

    event_a = provider.parse_webhook_event(payload=json.dumps(payload_a).encode())
    event_b = provider.parse_webhook_event(payload=json.dumps(payload_b).encode())

    assert event_a.provider_event_id != event_b.provider_event_id


def test_parse_webhook_event_rejects_malformed_json(provider):
    with pytest.raises(PaymentPermanentError):
        provider.parse_webhook_event(payload=b"not json{{{")


def test_parse_webhook_event_rejects_payload_with_no_entity(provider):
    payload = {"event": "subscription.activated", "created_at": 1, "payload": {}}
    with pytest.raises(PaymentPermanentError):
        provider.parse_webhook_event(payload=json.dumps(payload).encode())
