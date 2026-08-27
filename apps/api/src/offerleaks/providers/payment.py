"""Payment provider behind a `PaymentProvider` interface (architecture.md
§0.6's "providers-behind-interfaces" pattern, applied to billing).

Mirrors `providers/ai.py`: a `Protocol` every implementation must satisfy,
one concrete implementation (`RazorpayProvider`) that owns all vendor-SDK
details, and typed errors (`PaymentTransientError`/`PaymentPermanentError`,
subclassing the same `providers/errors.py` base classes as every other
provider) so `BillingService` can distinguish "retry" from "give up"
without knowing which vendor raised it -- exactly like the AI/OCR
providers already do.

No official `razorpay` SDK dependency is added: Razorpay's API is plain
REST+HMAC, and `httpx` (already a project dependency, moved from dev-only
to a runtime dependency by this change -- see pyproject.toml) is
sufficient, avoiding an extra dependency for what's a handful of endpoints
(architecture.md §19/§20: "do not add dependencies unless justified").
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from offerleaks.core.config import Settings
from offerleaks.providers.errors import PermanentProviderError, TransientProviderError

_RAZORPAY_API_BASE = "https://api.razorpay.com/v1"


class PaymentPermanentError(PermanentProviderError):
    pass


class PaymentTransientError(TransientProviderError):
    pass


class WebhookSignatureError(PaymentPermanentError):
    """The webhook payload's signature didn't match -- never trust or
    process the payload when this is raised (architecture.md §0.11)."""


@dataclass(frozen=True, slots=True)
class ProviderSubscription:
    """The subset of a Razorpay subscription object `BillingService`
    actually needs -- not a full passthrough of the vendor's response
    shape, so a Razorpay API field rename can't silently propagate into
    our domain layer."""

    provider_subscription_id: str
    status: str
    # Razorpay's "Subscription Link" -- a shareable payment-link-style
    # URL (their Subscription Links product), NOT a general-purpose
    # hosted checkout page for an in-app flow. The in-app authentication
    # path uses `provider_subscription_id` with Razorpay's client-side
    # Checkout.js, not this URL.
    short_url: str | None


@dataclass(frozen=True, slots=True)
class WebhookEventData:
    provider_event_id: str
    event_type: str
    payload: dict[str, Any]


class PaymentProvider(Protocol):
    async def create_customer(self, *, email: str, name: str) -> str:
        """Returns the provider's customer id, creating one if the user
        doesn't have one yet."""
        ...

    async def create_subscription(
        self, *, provider_plan_id: str, customer_id: str
    ) -> ProviderSubscription: ...

    async def cancel_subscription(
        self, *, provider_subscription_id: str, cancel_at_period_end: bool
    ) -> None: ...

    def verify_webhook_signature(self, *, payload: bytes, signature: str) -> bool: ...

    def parse_webhook_event(self, *, payload: bytes) -> WebhookEventData: ...


class RazorpayProvider:
    def __init__(self, settings: Settings) -> None:
        if not settings.razorpay_key_id or not settings.razorpay_key_secret:
            raise PaymentPermanentError(
                "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET are not configured"
            )
        self._key_id = settings.razorpay_key_id
        self._key_secret = settings.razorpay_key_secret
        self._webhook_secret = settings.razorpay_webhook_secret
        self._timeout = settings.razorpay_request_timeout_seconds

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=_RAZORPAY_API_BASE,
            auth=(self._key_id, self._key_secret),
            timeout=self._timeout,
        )

    async def _post(self, path: str, *, json_body: dict[str, Any]) -> dict[str, Any]:
        try:
            async with self._client() as client:
                response = await client.post(path, json=json_body)
        except httpx.TimeoutException as exc:
            raise PaymentTransientError(str(exc)) from exc
        except httpx.ConnectError as exc:
            raise PaymentTransientError(str(exc)) from exc

        if response.status_code == 429 or response.status_code >= 500:
            raise PaymentTransientError(
                f"Razorpay {path} returned {response.status_code}: {response.text}"
            )
        if response.status_code >= 400:
            raise PaymentPermanentError(
                f"Razorpay {path} returned {response.status_code}: {response.text}"
            )
        result: dict[str, Any] = response.json()
        return result

    async def create_customer(self, *, email: str, name: str) -> str:
        body = await self._post(
            "/customers",
            json_body={"name": name, "email": email, "fail_existing": "0"},
        )
        return str(body["id"])

    async def create_subscription(
        self, *, provider_plan_id: str, customer_id: str
    ) -> ProviderSubscription:
        # `total_count` is required by Razorpay's API for a subscription
        # even when billing is meant to run indefinitely -- 120 monthly
        # cycles (10 years) is Razorpay's own commonly-used convention
        # for "effectively unlimited," renewed by creating a fresh
        # subscription well before it would ever be reached.
        body = await self._post(
            "/subscriptions",
            json_body={
                "plan_id": provider_plan_id,
                "customer_id": customer_id,
                "total_count": 120,
                "customer_notify": 1,
            },
        )
        return ProviderSubscription(
            provider_subscription_id=str(body["id"]),
            status=str(body["status"]),
            short_url=body.get("short_url"),
        )

    async def cancel_subscription(
        self, *, provider_subscription_id: str, cancel_at_period_end: bool
    ) -> None:
        await self._post(
            f"/subscriptions/{provider_subscription_id}/cancel",
            json_body={"cancel_at_cycle_end": 1 if cancel_at_period_end else 0},
        )

    def verify_webhook_signature(self, *, payload: bytes, signature: str) -> bool:
        """Razorpay signs the raw request body with HMAC-SHA256 using the
        webhook secret configured in the dashboard (Settings -> Webhooks
        -> this endpoint's secret, distinct from the API key secret).
        The router calls this on the *raw bytes* before any JSON parsing
        -- parsing first and re-serializing to verify would not
        reliably reproduce the exact bytes Razorpay signed (key
        ordering, whitespace), so this must run on the untouched body.
        """
        if not self._webhook_secret:
            raise PaymentPermanentError("RAZORPAY_WEBHOOK_SECRET is not configured")

        expected = hmac.new(
            self._webhook_secret.encode("utf-8"), payload, hashlib.sha256
        ).hexdigest()
        # Constant-time comparison -- a naive `==` here would leak timing
        # information about how many leading bytes matched, the same
        # class of issue JWT/token comparisons elsewhere in this codebase
        # avoid.
        return hmac.compare_digest(expected, signature)

    def parse_webhook_event(self, *, payload: bytes) -> WebhookEventData:
        try:
            body = json.loads(payload)
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise PaymentPermanentError("malformed webhook payload") from exc

        event_type = body.get("event")
        # Razorpay does not send a single top-level "event id" field the
        # way some providers do; `account_id` + `created_at` + `event` is
        # not guaranteed unique, but the payload's own top-level entity
        # id (subscription/payment/etc, nested under
        # `payload.<entity>.entity.id`) combined with `event` and
        # `created_at` reliably is, and is what Razorpay itself
        # recommends using for idempotency. Built here, once, rather
        # than re-derived by every webhook handler branch.
        entity_id = _extract_first_entity_id(body.get("payload", {}))
        created_at = body.get("created_at")
        provider_event_id = f"{event_type}:{entity_id}:{created_at}"

        if not event_type or entity_id is None:
            raise PaymentPermanentError(f"webhook payload missing expected fields: {body!r}")

        return WebhookEventData(
            provider_event_id=provider_event_id, event_type=str(event_type), payload=body
        )


def _extract_first_entity_id(payload_section: dict[str, Any]) -> str | None:
    """Razorpay's webhook payload nests the affected entity under
    `payload.<entity_name>.entity`, e.g. `payload.subscription.entity.id`
    or `payload.payment.entity.id`. Returns the first entity id found,
    regardless of which entity key is present, since the shape varies by
    `event` type and the caller only needs *an* id, not a specific one.
    """
    for entity_wrapper in payload_section.values():
        entity = entity_wrapper.get("entity") if isinstance(entity_wrapper, dict) else None
        if isinstance(entity, dict) and "id" in entity:
            return str(entity["id"])
    return None
