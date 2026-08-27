"""Tests for `CompanyProfileService` (M7) -- the core resolution/cache/
refresh orchestration. Runs against real Postgres and Redis; the only
faked boundary is the two external providers (domain-age, website
reachability), via `tests/company/fakes.py`, same convention as the rest
of the suite's provider fakes.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from offerleaks.core.config import get_settings
from offerleaks.core.db import async_session_factory
from offerleaks.core.redis import redis_client
from offerleaks.models.company import CompanyVerificationStatus, ProviderCheckOutcome
from offerleaks.providers.website_reachability import WebsiteReachabilityResult
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.services.company_profile_service import CompanyProfileService

from .fakes import (
    FakeDomainAgeProvider,
    FakeWebsiteReachabilityProvider,
    registered_domain_result,
)


def _service(db, domain_age=None, website=None) -> CompanyProfileService:
    return CompanyProfileService(
        db,
        redis_client,
        domain_age or FakeDomainAgeProvider(),
        website or FakeWebsiteReachabilityProvider(),
    )


# --- Resolution edge cases ---


async def test_resolve_for_analysis_with_resolvable_sender_domain():
    async with async_session_factory() as db:
        company = await _service(db).resolve_for_analysis(
            sender_domain="hr@acme.com", company_name=None
        )
        await db.commit()

    assert company is not None
    assert company.domain == "acme.com"


async def test_resolve_for_analysis_with_company_name_but_no_domain():
    async with async_session_factory() as db:
        company = await _service(db).resolve_for_analysis(
            sender_domain=None, company_name="Acme Corp"
        )
        await db.commit()

    assert company is not None
    assert company.domain is None
    assert company.normalized_key == "name:acme"


async def test_resolve_for_analysis_returns_none_when_nothing_resolvable():
    async with async_session_factory() as db:
        company = await _service(db).resolve_for_analysis(sender_domain=None, company_name=None)
        await db.commit()

    assert company is None


async def test_resolve_for_analysis_with_malformed_domain_falls_back_to_none():
    async with async_session_factory() as db:
        company = await _service(db).resolve_for_analysis(
            sender_domain="not a domain", company_name=None
        )
        await db.commit()

    assert company is None


async def test_name_only_company_is_upgraded_in_place_once_a_domain_is_later_available():
    async with async_session_factory() as db:
        # First analysis: only a company name is extracted (no domain).
        first = await _service(db).resolve_for_analysis(
            sender_domain=None, company_name="Acme Corp"
        )
        await db.commit()
    assert first.domain is None
    assert first.normalized_key == "name:acme"

    async with async_session_factory() as db:
        # Second analysis, different user, has a domain for what is
        # (per the matching normalized name) presumably the same real
        # company -- the existing name-only row is upgraded onto the
        # domain-based identity *in place*, rather than creating a
        # second, disconnected `Company` the two would never merge into
        # (audit fix: this used to silently split one company into two
        # permanently-separate cached profiles).
        second = await _service(db).resolve_for_analysis(
            sender_domain="hr@acme.com", company_name="Acme Corp"
        )
        await db.commit()

    assert second.id == first.id
    assert second.domain == "acme.com"
    assert second.normalized_key == "domain:acme.com"

    # The old name-based key must no longer resolve to anything (it was
    # migrated, not duplicated).
    async with async_session_factory() as db:
        assert await CompanyRepository(db).get_by_key("name:acme") is None


async def test_upgrade_does_not_touch_a_company_that_already_has_a_different_domain():
    """A company that already has its *own* domain must never be
    silently repointed by a same-named upgrade attempt -- the guard is
    `WHERE domain IS NULL`, not "any name-only-looking row"."""
    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        existing = await repo.get_or_create_by_key(
            normalized_key="domain:already-has-domain.com",
            domain="already-has-domain.com",
            company_name="Acme Corp",
        )
        await db.commit()

    async with async_session_factory() as db:
        upgraded = await CompanyRepository(db).upgrade_name_only_company(
            company_id=existing.id,
            normalized_key="domain:someone-elses-domain.com",
            domain="someone-elses-domain.com",
        )
        await db.commit()

    # Guard didn't match (domain wasn't NULL) -- returns the existing,
    # unmodified row rather than corrupting it.
    assert upgraded.id == existing.id
    assert upgraded.domain == "already-has-domain.com"
    assert upgraded.normalized_key == "domain:already-has-domain.com"


async def test_concurrent_name_then_domain_resolution_never_produces_duplicate_companies():
    """Ten concurrent "I have a domain for this same-named company"
    resolutions racing against the same pre-existing name-only row --
    all must converge on exactly one upgraded `Company`, never a
    duplicate and never an unhandled unique-violation."""
    async with async_session_factory() as db:
        await CompanyRepository(db).get_or_create_by_key(
            normalized_key="name:racey merge co", domain=None, company_name="Racey Merge Co"
        )
        await db.commit()

    async def _resolve() -> uuid.UUID:
        async with async_session_factory() as db:
            company = await _service(db).resolve_for_analysis(
                sender_domain="hr@raceymerge.com", company_name="Racey Merge Co"
            )
            await db.commit()
            return company.id

    results = await asyncio.gather(*[_resolve() for _ in range(10)])

    assert len(set(results)) == 1
    async with async_session_factory() as db:
        winner = await CompanyRepository(db).get_by_id(results[0])
    assert winner is not None
    assert winner.domain == "raceymerge.com"


async def test_repeated_domain_resolution_reuses_the_same_company_without_duplicate_rows():
    async with async_session_factory() as db:
        a = await _service(db).resolve_for_analysis(
            sender_domain="hr@acme.com", company_name="Acme Corp"
        )
        await db.commit()

    async with async_session_factory() as db:
        b = await _service(db).resolve_for_analysis(
            sender_domain="recruiting@acme.com", company_name="Acme Corporation"
        )
        await db.commit()

    assert a.id == b.id


# --- Cache correctness ---


async def test_cache_miss_falls_back_to_postgres_and_repopulates_redis():
    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        company = await repo.get_or_create_by_key(
            normalized_key="domain:cached.com", domain="cached.com", company_name="Cached Co"
        )
        await repo.upsert_signal(
            company_id=company.id,
            verification_status=CompanyVerificationStatus.FOUND,
            domain_age_days=500,
            domain_registered_at=datetime.now(UTC) - timedelta(days=500),
            domain_age_check=ProviderCheckOutcome.OK.value,
            website_reachable=True,
            website_reachability_check=ProviderCheckOutcome.OK.value,
            email_domain_match=True,
            evidence_ratio=1.0,
            last_checked_at=datetime.now(UTC),
        )
        await db.commit()

    assert await redis_client.get(f"company_profile:{company.normalized_key}") is None

    async with async_session_factory() as db:
        profile = await _service(db).get_profile(company)

    assert profile is not None
    assert profile.verification_status == CompanyVerificationStatus.FOUND
    assert profile.domain_age_days == 500
    # Repopulated into Redis by the read above.
    assert await redis_client.get(f"company_profile:{company.normalized_key}") is not None


async def test_cache_hit_returns_cached_value_without_touching_postgres_signal():
    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        company = await repo.get_or_create_by_key(
            normalized_key="domain:hit.com", domain="hit.com", company_name="Hit Co"
        )
        await repo.upsert_signal(
            company_id=company.id,
            verification_status=CompanyVerificationStatus.FOUND,
            domain_age_days=10,
            domain_registered_at=datetime.now(UTC),
            domain_age_check=ProviderCheckOutcome.OK.value,
            website_reachable=True,
            website_reachability_check=ProviderCheckOutcome.OK.value,
            email_domain_match=None,
            evidence_ratio=1.0,
            last_checked_at=datetime.now(UTC),
        )
        await db.commit()
        # Warm the cache.
        await _service(db).get_profile(company)

    # Now mutate Postgres directly, bypassing the cache -- if a
    # subsequent read is a true cache hit, it must still report the
    # *old* (cached) value, not the freshly-written one.
    async with async_session_factory() as db:
        await CompanyRepository(db).upsert_signal(
            company_id=company.id,
            verification_status=CompanyVerificationStatus.NOT_FOUND,
            domain_age_days=None,
            domain_registered_at=None,
            domain_age_check=ProviderCheckOutcome.NO_RECORD.value,
            website_reachable=None,
            website_reachability_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
            email_domain_match=None,
            evidence_ratio=0.5,
            last_checked_at=datetime.now(UTC),
        )
        await db.commit()

    async with async_session_factory() as db:
        profile = await _service(db).get_profile(company)

    assert profile is not None
    assert profile.verification_status == CompanyVerificationStatus.FOUND  # the stale cached value


async def test_invalid_cache_entry_is_ignored_and_falls_back_to_postgres():
    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        company = await repo.get_or_create_by_key(
            normalized_key="domain:corrupt.com", domain="corrupt.com", company_name="Corrupt Co"
        )
        await repo.upsert_signal(
            company_id=company.id,
            verification_status=CompanyVerificationStatus.FOUND,
            domain_age_days=5,
            domain_registered_at=datetime.now(UTC),
            domain_age_check=ProviderCheckOutcome.OK.value,
            website_reachable=True,
            website_reachability_check=ProviderCheckOutcome.OK.value,
            email_domain_match=None,
            evidence_ratio=1.0,
            last_checked_at=datetime.now(UTC),
        )
        await db.commit()

    await redis_client.set(f"company_profile:{company.normalized_key}", "{not valid json")

    async with async_session_factory() as db:
        profile = await _service(db).get_profile(company)

    assert profile is not None
    assert profile.verification_status == CompanyVerificationStatus.FOUND


async def test_get_profile_returns_none_when_never_checked_at_all():
    async with async_session_factory() as db:
        company = await CompanyRepository(db).get_or_create_by_key(
            normalized_key="domain:neverchecked.com",
            domain="neverchecked.com",
            company_name=None,
        )
        await db.commit()

    async with async_session_factory() as db:
        profile = await _service(db).get_profile(company)

    assert profile is None


# --- Provider degradation / insufficient-evidence honesty ---


async def test_perform_refresh_with_registered_domain_and_reachable_site_is_found():
    async with async_session_factory() as db:
        company = await CompanyRepository(db).get_or_create_by_key(
            normalized_key="domain:realco.com", domain="realco.com", company_name="Real Co"
        )
        await db.commit()

    domain_age = FakeDomainAgeProvider(
        responses={"realco.com": registered_domain_result(datetime.now(UTC) - timedelta(days=3000))}
    )
    website = FakeWebsiteReachabilityProvider(
        responses={
            "realco.com": WebsiteReachabilityResult(
                reachable=True, outcome=ProviderCheckOutcome.OK
            )
        }
    )

    async with async_session_factory() as db:
        signal = await _service(db, domain_age, website).perform_refresh(company)
        await db.commit()

    assert signal.verification_status == CompanyVerificationStatus.FOUND
    assert signal.domain_age_days is not None and signal.domain_age_days > 2900


async def test_perform_refresh_with_no_registration_record_is_not_found():
    async with async_session_factory() as db:
        company = await CompanyRepository(db).get_or_create_by_key(
            normalized_key="domain:noregistration.com",
            domain="noregistration.com",
            company_name=None,
        )
        await db.commit()

    async with async_session_factory() as db:
        signal = await _service(db).perform_refresh(company)  # default fake returns NO_RECORD
        await db.commit()

    assert signal.verification_status == CompanyVerificationStatus.NOT_FOUND


async def test_perform_refresh_degrades_to_insufficient_evidence_on_provider_timeout():
    """Both providers fail -- must NEVER fabricate NOT_FOUND."""
    async with async_session_factory() as db:
        company = await CompanyRepository(db).get_or_create_by_key(
            normalized_key="domain:flaky.com", domain="flaky.com", company_name=None
        )
        await db.commit()

    domain_age = FakeDomainAgeProvider(raise_transient_for={"flaky.com"})
    website = FakeWebsiteReachabilityProvider(raise_for={"flaky.com"})

    async with async_session_factory() as db:
        signal = await _service(db, domain_age, website).perform_refresh(company)
        await db.commit()

    assert signal.verification_status == CompanyVerificationStatus.INSUFFICIENT_EVIDENCE
    assert signal.domain_age_days is None
    assert signal.website_reachable is None
    assert signal.evidence_ratio == 0.0


async def test_perform_refresh_with_no_domain_at_all_is_insufficient_evidence():
    """A company resolved by name only (no domain evidence) can never
    honestly be checked externally -- must not fabricate a risk number
    or a Not Found."""
    async with async_session_factory() as db:
        company = await CompanyRepository(db).get_or_create_by_key(
            normalized_key="name:mystery-co", domain=None, company_name="Mystery Co"
        )
        await db.commit()

    async with async_session_factory() as db:
        signal = await _service(db).perform_refresh(company)
        await db.commit()

    assert signal.verification_status == CompanyVerificationStatus.INSUFFICIENT_EVIDENCE
    assert signal.domain_age_days is None
    assert signal.website_reachable is None


async def test_perform_refresh_preserves_existing_email_domain_match():
    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        company = await repo.get_or_create_by_key(
            normalized_key="domain:preserve.com", domain="preserve.com", company_name=None
        )
        await repo.upsert_signal(
            company_id=company.id,
            verification_status=CompanyVerificationStatus.INSUFFICIENT_EVIDENCE,
            domain_age_days=None,
            domain_registered_at=None,
            domain_age_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
            website_reachable=None,
            website_reachability_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
            email_domain_match=True,
            evidence_ratio=0.0,
            last_checked_at=datetime.now(UTC) - timedelta(days=30),
        )
        await db.commit()

    async with async_session_factory() as db:
        signal = await _service(db).perform_refresh(company)
        await db.commit()

    assert signal.email_domain_match is True


# --- Concurrency: locking / rate limiting on refresh dispatch ---


async def test_ensure_fresh_only_enqueues_once_for_concurrent_callers():
    """Simulates several concurrent requests noticing the same
    never-checked company at once -- only one should win the refresh
    lock and enqueue a job."""
    import offerleaks.services.company_profile_service as module

    enqueued: list[str] = []

    class _FakeQueue:
        def enqueue(self, *args, **kwargs):
            enqueued.append(args[1])

    original_get_queue = module.get_company_queue
    module.get_company_queue = lambda: _FakeQueue()
    try:
        async with async_session_factory() as db:
            company = await CompanyRepository(db).get_or_create_by_key(
                normalized_key="domain:racey-refresh.com",
                domain="racey-refresh.com",
                company_name=None,
            )
            await db.commit()

        async def _attempt():
            async with async_session_factory() as db:
                await _service(db).ensure_fresh(company)
                await db.commit()

        await asyncio.gather(*[_attempt() for _ in range(5)])
    finally:
        module.get_company_queue = original_get_queue

    assert len(enqueued) == 1
    assert enqueued[0] == str(company.id)


async def test_ensure_fresh_does_nothing_when_cache_is_already_fresh():
    import offerleaks.services.company_profile_service as module

    enqueued: list[str] = []

    class _FakeQueue:
        def enqueue(self, *args, **kwargs):
            enqueued.append(args[1])

    original_get_queue = module.get_company_queue
    module.get_company_queue = lambda: _FakeQueue()
    try:
        async with async_session_factory() as db:
            repo = CompanyRepository(db)
            company = await repo.get_or_create_by_key(
                normalized_key="domain:fresh.com", domain="fresh.com", company_name=None
            )
            await repo.upsert_signal(
                company_id=company.id,
                verification_status=CompanyVerificationStatus.FOUND,
                domain_age_days=100,
                domain_registered_at=datetime.now(UTC),
                domain_age_check=ProviderCheckOutcome.OK.value,
                website_reachable=True,
                website_reachability_check=ProviderCheckOutcome.OK.value,
                email_domain_match=None,
                evidence_ratio=1.0,
                last_checked_at=datetime.now(UTC),
            )
            await db.commit()

        async with async_session_factory() as db:
            await _service(db).ensure_fresh(company)
            await db.commit()
    finally:
        module.get_company_queue = original_get_queue

    assert enqueued == []


async def test_ensure_fresh_respects_the_outbound_rate_limit_budget():
    import offerleaks.services.company_profile_service as module

    enqueued: list[str] = []

    class _FakeQueue:
        def enqueue(self, *args, **kwargs):
            enqueued.append(args[1])

    settings = get_settings()
    original_limit = settings.company_lookup_rate_limit_per_minute
    settings.company_lookup_rate_limit_per_minute = 1
    original_get_queue = module.get_company_queue
    module.get_company_queue = lambda: _FakeQueue()
    try:
        companies = []
        async with async_session_factory() as db:
            repo = CompanyRepository(db)
            for i in range(3):
                companies.append(
                    await repo.get_or_create_by_key(
                        normalized_key=f"domain:budget{i}.com",
                        domain=f"budget{i}.com",
                        company_name=None,
                    )
                )
            await db.commit()

        for company in companies:
            async with async_session_factory() as db:
                await _service(db).ensure_fresh(company)
                await db.commit()
    finally:
        settings.company_lookup_rate_limit_per_minute = original_limit
        module.get_company_queue = original_get_queue

    # Only the first should have made it under the budget of 1/minute.
    assert len(enqueued) == 1
