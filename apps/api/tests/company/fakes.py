"""Fake `DomainAgeProvider`/`WebsiteReachabilityProvider` implementations
for M7 tests -- same "swap the external boundary via a fake, not a mock
of internal calls" convention as `tests/analyses/fakes.py` and
`tests/billing/`'s fake payment provider.
"""

from datetime import datetime

from offerleaks.models.company import ProviderCheckOutcome
from offerleaks.providers.domain_age import (
    DomainAgePermanentError,
    DomainAgeResult,
    DomainAgeTransientError,
)
from offerleaks.providers.website_reachability import WebsiteReachabilityResult


class FakeDomainAgeProvider:
    """Scripted responses keyed by domain. `raise_transient`/
    `raise_permanent` let a test simulate provider degradation without
    touching the real network."""

    def __init__(
        self,
        *,
        responses: dict[str, DomainAgeResult] | None = None,
        raise_transient_for: set[str] | None = None,
        raise_permanent_for: set[str] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.raise_transient_for = raise_transient_for or set()
        self.raise_permanent_for = raise_permanent_for or set()
        self.calls: list[str] = []

    async def lookup(self, *, domain: str) -> DomainAgeResult:
        self.calls.append(domain)
        if domain in self.raise_transient_for:
            raise DomainAgeTransientError(f"fake transient failure for {domain}")
        if domain in self.raise_permanent_for:
            raise DomainAgePermanentError(f"fake permanent failure for {domain}")
        if domain in self.responses:
            return self.responses[domain]
        return DomainAgeResult(registered_at=None, outcome=ProviderCheckOutcome.NO_RECORD)


def registered_domain_result(registered_at: datetime) -> DomainAgeResult:
    return DomainAgeResult(registered_at=registered_at, outcome=ProviderCheckOutcome.OK)


class FakeWebsiteReachabilityProvider:
    def __init__(
        self,
        *,
        responses: dict[str, WebsiteReachabilityResult] | None = None,
        raise_for: set[str] | None = None,
    ) -> None:
        self.responses = responses or {}
        self.raise_for = raise_for or set()
        self.calls: list[str] = []

    async def check(self, *, domain: str) -> WebsiteReachabilityResult:
        self.calls.append(domain)
        if domain in self.raise_for:
            raise RuntimeError(f"fake failure checking {domain}")
        if domain in self.responses:
            return self.responses[domain]
        return WebsiteReachabilityResult(reachable=True, outcome=ProviderCheckOutcome.OK)
