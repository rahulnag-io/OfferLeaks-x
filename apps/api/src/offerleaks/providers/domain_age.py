"""Domain-age lookup behind a `DomainAgeProvider` interface (M7: Company
Signal & Reputation), following the same provider-abstraction pattern as
`OCRProvider`/`AIProvider`/`PaymentProvider` (architecture.md §0.13) --
nothing outside this module talks to RDAP directly, so swapping in a
paid WHOIS vendor later is a new provider class + a config change.

RDAP (Registration Data Access Protocol, RFC 7482) is used instead of
raw WHOIS: it's free, requires no API key or account, returns structured
JSON instead of vendor-specific free-text WHOIS output, and is the
IETF-standardized successor WHOIS registries are migrating to -- exactly
the "one free/cheap WHOIS-type API" M7 asks for, without a bespoke
per-registrar text parser.
"""

from datetime import UTC, datetime
from typing import Protocol

import httpx

from offerleaks.core.config import Settings
from offerleaks.models.company import ProviderCheckOutcome
from offerleaks.providers.errors import PermanentProviderError, TransientProviderError


class DomainAgePermanentError(PermanentProviderError):
    pass


class DomainAgeTransientError(TransientProviderError):
    pass


class DomainAgeResult:
    """Deliberately not the raw provider payload -- only the single
    derived fact this product needs (M7 §11/§15: never expose or persist
    raw WHOIS/RDAP data, which can carry unrelated registrant PII).
    `registered_at=None, outcome=NO_RECORD` means the lookup succeeded
    but the registry has no record for the domain -- a genuine negative,
    not a failure."""

    __slots__ = ("registered_at", "outcome")

    def __init__(self, *, registered_at: datetime | None, outcome: ProviderCheckOutcome) -> None:
        self.registered_at = registered_at
        self.outcome = outcome

    @property
    def age_days(self) -> int | None:
        if self.registered_at is None:
            return None
        return (datetime.now(UTC) - self.registered_at).days


class DomainAgeProvider(Protocol):
    async def lookup(self, *, domain: str) -> DomainAgeResult: ...


class RDAPDomainAgeProvider:
    """Queries `{rdap_base_url}/{domain}` (rdap.org's free bootstrap
    proxy by default -- it forwards to the correct registry's own RDAP
    server per IANA's bootstrap registry, so this doesn't need per-TLD
    endpoint configuration). No credentials required."""

    def __init__(self, settings: Settings) -> None:
        self._base_url = settings.rdap_base_url.rstrip("/")
        self._timeout = settings.domain_age_request_timeout_seconds

    async def lookup(self, *, domain: str) -> DomainAgeResult:
        url = f"{self._base_url}/{domain}"
        try:
            # `follow_redirects=True` is deliberate and safe here (unlike
            # the website-reachability provider, which must *not*
            # auto-follow -- see that module): this client only ever
            # talks to one fixed, trusted, operator-configured endpoint,
            # never a user- or document-influenced URL, so there's no
            # SSRF surface to redirect into. It's required in practice:
            # rdap.org's public bootstrap service works by issuing an
            # HTTP redirect to the domain's actual authoritative
            # registry rather than transparently proxying the response,
            # and httpx defaults to *not* following redirects.
            async with httpx.AsyncClient(timeout=self._timeout, follow_redirects=True) as client:
                response = await client.get(url, headers={"Accept": "application/rdap+json"})
        except httpx.TimeoutException as exc:
            raise DomainAgeTransientError(f"RDAP lookup timed out for {domain}") from exc
        except httpx.HTTPError as exc:
            raise DomainAgeTransientError(f"RDAP lookup failed for {domain}: {exc}") from exc

        if response.status_code == 404:
            # A well-formed "no record" response -- the registry was
            # reached and definitively has nothing for this domain. Not
            # an error path: this is a real, evidenced negative.
            return DomainAgeResult(registered_at=None, outcome=ProviderCheckOutcome.NO_RECORD)
        if response.status_code == 429:
            raise DomainAgeTransientError(f"RDAP rate-limited for {domain}")
        if response.status_code >= 500:
            raise DomainAgeTransientError(
                f"RDAP server error {response.status_code} for {domain}"
            )
        if response.status_code != 200:
            raise DomainAgePermanentError(
                f"Unexpected RDAP status {response.status_code} for {domain}"
            )

        try:
            payload = response.json()
        except ValueError as exc:
            raise DomainAgeTransientError(f"RDAP returned malformed JSON for {domain}") from exc

        registered_at = self._extract_registration_date(payload)
        if registered_at is None:
            # Reached the registry, got a 200, but couldn't find a
            # registration event in the shape we understand -- an
            # honest "insufficient evidence," not a fabricated found/
            # not-found result.
            return DomainAgeResult(
                registered_at=None, outcome=ProviderCheckOutcome.MALFORMED_RESPONSE
            )
        return DomainAgeResult(registered_at=registered_at, outcome=ProviderCheckOutcome.OK)

    @staticmethod
    def _extract_registration_date(payload: object) -> datetime | None:
        """RDAP's `events` array carries a `{"eventAction": "registration",
        "eventDate": "<ISO 8601>"}` entry per RFC 9083 §4.5 -- this reads
        only that one field, nothing else from the payload is retained."""
        if not isinstance(payload, dict):
            return None
        events = payload.get("events")
        if not isinstance(events, list):
            return None

        for event in events:
            if not isinstance(event, dict):
                continue
            if event.get("eventAction") != "registration":
                continue
            raw_date = event.get("eventDate")
            if not isinstance(raw_date, str):
                continue
            try:
                parsed = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=UTC)
            return parsed

        return None
