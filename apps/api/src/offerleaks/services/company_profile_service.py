"""Company profile resolution, caching, and refresh orchestration (M7:
Company Signal & Reputation).

This is the one reusable service every entry point (the analysis worker,
and -- for `refresh_company_profile` -- the RQ worker) goes through;
routers/other services never touch `CompanyRepository` or the domain-age/
website providers directly (architecture.md §0.3's service-ownership
convention).

Caching model: Redis is a read-accelerating cache in front of Postgres,
never a second source of truth. A cache read that misses always falls
back to Postgres and repopulates Redis from it (so a Redis restart/
flush is self-healing, per M7's "profile survives application
restarts"). A cache read that hits is returned as-is -- callers never
pay for a second external lookup just because they happened to read a
company mid-refresh.

Concurrency model: a Redis `SET NX PX` lock per normalized company key
gates who gets to *enqueue* a refresh; the lock's own TTL is the backstop
against a crashed/never-run job leaving the company stuck un-refreshable
forever (no explicit unlock needed for that reason -- it expires on its
own). A separate, global fixed-window Redis counter caps how many
refreshes can be enqueued per minute system-wide (M7 §17 cost control),
independent of the per-company lock.
"""

import json
import logging
import time
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.core.config import Settings, get_settings
from offerleaks.core.queue import get_company_queue
from offerleaks.models.company import (
    Company,
    CompanySignal,
    CompanyVerificationStatus,
    ProviderCheckOutcome,
)
from offerleaks.providers.domain_age import (
    DomainAgePermanentError,
    DomainAgeProvider,
    DomainAgeTransientError,
)
from offerleaks.providers.website_reachability import WebsiteReachabilityProvider
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.services.company_normalization import (
    normalize_company_name,
    normalize_domain,
    resolve_identity_key,
)

logger = logging.getLogger(__name__)

# Backdates a placeholder signal row far enough that `ensure_fresh`'s
# staleness check always treats it as stale under any realistic
# `company_profile_stale_after_seconds` value -- this row represents
# "not checked yet," not a completed, merely-old check.
_NEVER_CHECKED_SENTINEL = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class CompanyProfileData:
    """Cache/DB-source-agnostic view of a company's current signal set --
    what `api/routers/analyses.py` actually reads to build the response.
    `None` for every advanced field means "insufficient evidence for
    that specific signal," independent of the overall
    `verification_status`."""

    company_name: str | None
    domain: str | None
    verification_status: CompanyVerificationStatus
    last_checked_at: datetime
    domain_age_days: int | None
    website_reachable: bool | None
    email_domain_match: bool | None


def _cache_key(normalized_key: str) -> str:
    return f"company_profile:{normalized_key}"


def _lock_key(normalized_key: str) -> str:
    return f"company_lookup_lock:{normalized_key}"


class CompanyProfileService:
    def __init__(
        self,
        db: AsyncSession,
        redis: Redis,
        domain_age_provider: DomainAgeProvider,
        website_provider: WebsiteReachabilityProvider,
        settings: Settings | None = None,
    ) -> None:
        self._db = db
        self._companies = CompanyRepository(db)
        self._redis = redis
        self._domain_age = domain_age_provider
        self._website = website_provider
        self._settings = settings or get_settings()

    # --- Resolution (fast, DB-only; called inline from the analysis worker) ---

    async def resolve_for_analysis(
        self, *, sender_domain: str | None, company_name: str | None
    ) -> Company | None:
        """Resolves (creating if necessary) the shared `Company` row for
        this analysis's extracted signals, and opportunistically triggers
        a background refresh if the cached profile is missing or stale.
        Returns `None` when there is genuinely nothing to resolve (M7's
        honest "no resolvable domain or company name" case) -- the caller
        must not fabricate a `Company` row for that.
        """
        normalized_domain = normalize_domain(sender_domain)
        normalized_name = normalize_company_name(company_name)
        key = resolve_identity_key(domain=sender_domain, company_name=company_name)
        if key is None:
            return None

        company: Company | None = None
        if normalized_domain is not None and normalized_name is not None:
            # A domain is always preferred as the identity key for a
            # *new* company -- but if a same-named company was already
            # resolved by name alone (no domain evidence yet, from an
            # earlier analysis), upgrade that existing row onto the
            # domain-based key in place, rather than creating a second,
            # disconnected `Company` the two would never merge into.
            existing_by_domain = await self._companies.get_by_key(key)
            if existing_by_domain is None:
                name_key = f"name:{normalized_name}"
                existing_by_name = await self._companies.get_by_key(name_key)
                if existing_by_name is not None and existing_by_name.domain is None:
                    company = await self._companies.upgrade_name_only_company(
                        company_id=existing_by_name.id,
                        normalized_key=key,
                        domain=normalized_domain,
                    )

        if company is None:
            company = await self._companies.get_or_create_by_key(
                normalized_key=key, domain=normalized_domain, company_name=company_name
            )

        # A company first resolved by name alone (no domain evidence yet)
        # can be strengthened by a later analysis that has one -- the
        # branch above already handles migrating the row's *identity*
        # key; this covers the (rarer) case where the row already has
        # the domain-based key but `domain` itself wasn't set for some
        # reason. Additive only, never overwrites a domain the company
        # already has.
        if company.domain is None and normalized_domain is not None:
            company.domain = normalized_domain
            await self._db.flush()

        domain_matches: bool | None = None
        if company.domain is not None and normalized_domain is not None:
            domain_matches = company.domain == normalized_domain

        existing_signal = await self._companies.get_signal(company.id)
        if existing_signal is not None:
            await self._companies.set_email_domain_match(
                company_id=company.id, matches=domain_matches
            )
        else:
            # First time this company has ever been resolved: there's no
            # signal row for `set_email_domain_match` to update yet, and
            # by the time the eventual background refresh runs (a
            # separate job, with only `company_id` to go on -- see
            # `perform_refresh`), *this* analysis's sender domain is gone
            # and unrecoverable. Create a placeholder signal row now so
            # the email-domain-match evidence isn't silently lost.
            # `last_checked_at` is deliberately backdated so `ensure_fresh`
            # still treats this as stale and enqueues a real,
            # provider-backed refresh -- this placeholder is not itself a
            # completed check.
            await self._companies.upsert_signal(
                company_id=company.id,
                verification_status=CompanyVerificationStatus.INSUFFICIENT_EVIDENCE,
                domain_age_days=None,
                domain_registered_at=None,
                domain_age_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
                website_reachable=None,
                website_reachability_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
                email_domain_match=domain_matches,
                evidence_ratio=0.0,
                last_checked_at=_NEVER_CHECKED_SENTINEL,
            )

        await self.ensure_fresh(company)
        return company

    # --- Cache-aware read ---

    async def get_profile(self, company: Company) -> CompanyProfileData | None:
        cached = await self._read_cache(company.normalized_key)
        if cached is not None:
            return cached

        signal = await self._companies.get_signal(company.id)
        if signal is None:
            return None

        data = CompanyProfileData(
            company_name=company.company_name,
            domain=company.domain,
            verification_status=signal.verification_status,
            last_checked_at=signal.last_checked_at,
            domain_age_days=signal.domain_age_days,
            website_reachable=signal.website_reachable,
            email_domain_match=signal.email_domain_match,
        )
        await self._write_cache(company.normalized_key, data)
        return data

    # --- Staleness / refresh dispatch ---

    async def ensure_fresh(self, company: Company) -> None:
        """Enqueues a background refresh iff the profile is missing or
        stale *and* nobody else is already refreshing it *and* the
        system-wide outbound-lookup budget for this minute isn't
        exhausted. Never blocks the caller on the refresh itself --
        `get_profile` above is always safe to call immediately after,
        and will simply report `INSUFFICIENT_EVIDENCE`/stale data until
        the background job completes.
        """
        if await self._read_cache(company.normalized_key) is not None:
            return  # fresh in Redis -- nothing to do

        signal = await self._companies.get_signal(company.id)
        now = datetime.now(UTC)
        stale = signal is None or (
            (now - signal.last_checked_at).total_seconds()
            > self._settings.company_profile_stale_after_seconds
        )
        if not stale:
            # Valid Postgres row, just not (yet) in Redis -- repopulate
            # the cache from it rather than triggering any lookup.
            data = CompanyProfileData(
                company_name=company.company_name,
                domain=company.domain,
                verification_status=signal.verification_status,  # type: ignore[union-attr]
                last_checked_at=signal.last_checked_at,  # type: ignore[union-attr]
                domain_age_days=signal.domain_age_days,  # type: ignore[union-attr]
                website_reachable=signal.website_reachable,  # type: ignore[union-attr]
                email_domain_match=signal.email_domain_match,  # type: ignore[union-attr]
            )
            await self._write_cache(company.normalized_key, data)
            return

        if not await self._try_acquire_lock(company.normalized_key):
            return  # another request/job is already refreshing this company
        if not await self._try_consume_rate_budget():
            logger.info(
                "company lookup rate budget exhausted; deferring refresh for %s",
                company.normalized_key,
            )
            return

        get_company_queue().enqueue(
            "offerleaks.worker.process_company_refresh",
            str(company.id),
            job_timeout=self._settings.company_refresh_job_timeout_seconds,
        )

    # --- The actual provider-calling work (runs inside the RQ job) ---

    async def perform_refresh(self, company: Company) -> CompanySignal:
        domain = company.domain
        if domain is None:
            # Name-only company: nothing external to check at all. Honest
            # insufficient-evidence, not a guess.
            signal = await self._companies.upsert_signal(
                company_id=company.id,
                verification_status=CompanyVerificationStatus.INSUFFICIENT_EVIDENCE,
                domain_age_days=None,
                domain_registered_at=None,
                domain_age_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
                website_reachable=None,
                website_reachability_check=ProviderCheckOutcome.NOT_CONFIGURED.value,
                email_domain_match=None,
                evidence_ratio=0.0,
                last_checked_at=datetime.now(UTC),
            )
            await self._write_cache_from_signal(company, signal)
            return signal

        age_days: int | None = None
        registered_at = None
        try:
            age_result = await self._domain_age.lookup(domain=domain)
            domain_age_outcome = age_result.outcome
            age_days = age_result.age_days
            registered_at = age_result.registered_at
        except DomainAgeTransientError as exc:
            logger.warning("domain-age lookup transiently failed for %s: %s", domain, exc)
            domain_age_outcome = ProviderCheckOutcome.TIMEOUT
        except DomainAgePermanentError as exc:
            logger.warning("domain-age lookup permanently failed for %s: %s", domain, exc)
            domain_age_outcome = ProviderCheckOutcome.UNAVAILABLE

        reachable: bool | None = None
        try:
            website_result = await self._website.check(domain=domain)
            website_outcome = website_result.outcome
            reachable = website_result.reachable
        except Exception as exc:  # noqa: BLE001 - defensive, never let this fail the refresh
            logger.warning("website reachability check failed for %s: %s", domain, exc)
            website_outcome = ProviderCheckOutcome.UNAVAILABLE

        evidenced = 0
        if domain_age_outcome in (ProviderCheckOutcome.OK, ProviderCheckOutcome.NO_RECORD):
            evidenced += 1
        if website_outcome == ProviderCheckOutcome.OK:
            evidenced += 1
        evidence_ratio = evidenced / 2

        if domain_age_outcome == ProviderCheckOutcome.NO_RECORD:
            # RDAP definitively has no registration record for this
            # domain -- a real, evidenced negative.
            status = CompanyVerificationStatus.NOT_FOUND
        elif domain_age_outcome == ProviderCheckOutcome.OK or (
            website_outcome == ProviderCheckOutcome.OK and reachable
        ):
            status = CompanyVerificationStatus.FOUND
        else:
            # Both providers failed/timed out/rate-limited -- honest
            # "we don't know," never coerced to Not Found.
            status = CompanyVerificationStatus.INSUFFICIENT_EVIDENCE

        existing_signal = await self._companies.get_signal(company.id)
        preserved_email_match = (
            existing_signal.email_domain_match if existing_signal is not None else None
        )

        signal = await self._companies.upsert_signal(
            company_id=company.id,
            verification_status=status,
            domain_age_days=age_days,
            domain_registered_at=registered_at,
            domain_age_check=domain_age_outcome.value,
            website_reachable=reachable,
            website_reachability_check=website_outcome.value,
            email_domain_match=preserved_email_match,
            evidence_ratio=evidence_ratio,
            last_checked_at=datetime.now(UTC),
        )
        await self._write_cache_from_signal(company, signal)
        return signal

    # --- Redis plumbing ---

    async def _read_cache(self, normalized_key: str) -> CompanyProfileData | None:
        try:
            raw = await self._redis.get(_cache_key(normalized_key))
        except Exception as exc:  # noqa: BLE001 - Redis being down must degrade, not crash a request
            logger.warning("company profile cache read failed for %s: %s", normalized_key, exc)
            return None
        if raw is None:
            return None
        try:
            payload = json.loads(raw)
            return CompanyProfileData(
                company_name=payload["company_name"],
                domain=payload["domain"],
                verification_status=CompanyVerificationStatus(payload["verification_status"]),
                last_checked_at=datetime.fromisoformat(payload["last_checked_at"]),
                domain_age_days=payload["domain_age_days"],
                website_reachable=payload["website_reachable"],
                email_domain_match=payload["email_domain_match"],
            )
        except (KeyError, ValueError, TypeError) as exc:
            logger.warning("corrupt company profile cache entry for %s: %s", normalized_key, exc)
            return None

    async def _write_cache(self, normalized_key: str, data: CompanyProfileData) -> None:
        payload = {
            "company_name": data.company_name,
            "domain": data.domain,
            "verification_status": data.verification_status.value,
            "last_checked_at": data.last_checked_at.isoformat(),
            "domain_age_days": data.domain_age_days,
            "website_reachable": data.website_reachable,
            "email_domain_match": data.email_domain_match,
        }
        try:
            await self._redis.set(
                _cache_key(normalized_key),
                json.dumps(payload),
                ex=self._settings.company_profile_redis_ttl_seconds,
            )
        except Exception as exc:  # noqa: BLE001 - cache writes are best-effort
            logger.warning("company profile cache write failed for %s: %s", normalized_key, exc)

    async def _write_cache_from_signal(self, company: Company, signal: CompanySignal) -> None:
        await self._write_cache(
            company.normalized_key,
            CompanyProfileData(
                company_name=company.company_name,
                domain=company.domain,
                verification_status=signal.verification_status,
                last_checked_at=signal.last_checked_at,
                domain_age_days=signal.domain_age_days,
                website_reachable=signal.website_reachable,
                email_domain_match=signal.email_domain_match,
            ),
        )

    async def _try_acquire_lock(self, normalized_key: str) -> bool:
        try:
            acquired = await self._redis.set(
                _lock_key(normalized_key),
                "1",
                nx=True,
                px=self._settings.company_lookup_lock_seconds * 1000,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("company lookup lock unavailable for %s: %s", normalized_key, exc)
            # Redis being down shouldn't block resolution entirely, but it
            # also means we can't safely dedupe concurrent refreshes --
            # err on the side of *not* enqueueing rather than risking an
            # uncontrolled fan-out of external calls.
            return False
        return bool(acquired)

    async def _try_consume_rate_budget(self) -> bool:
        window = int(time.time() // 60)
        key = f"company_lookup_rate:{window}"
        try:
            current = await self._redis.incr(key)
            if current == 1:
                await self._redis.expire(key, 60)
        except Exception as exc:  # noqa: BLE001
            logger.warning("company lookup rate counter unavailable: %s", exc)
            return False
        return current <= self._settings.company_lookup_rate_limit_per_minute
