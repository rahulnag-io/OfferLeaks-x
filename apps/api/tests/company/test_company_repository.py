"""Tests for `CompanyRepository` against real Postgres (M7).

`test_concurrent_get_or_create_never_produces_duplicate_companies` is the
one that matters most: it's the actual proof behind the M7 DoD claim
("two users uploading offers from the same company... without a second
external lookup" starts from "...without a second *company row*
either").
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from offerleaks.core.db import async_session_factory
from offerleaks.models.company import CompanyVerificationStatus, ProviderCheckOutcome
from offerleaks.repositories.company_repository import CompanyRepository


async def test_get_or_create_by_key_is_idempotent():
    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        first = await repo.get_or_create_by_key(
            normalized_key="domain:acme.com", domain="acme.com", company_name="Acme"
        )
        second = await repo.get_or_create_by_key(
            normalized_key="domain:acme.com", domain="acme.com", company_name="Acme"
        )
        await db.commit()

    assert first.id == second.id


async def test_concurrent_get_or_create_never_produces_duplicate_companies():
    """Ten concurrent "first time seeing this company" resolutions, each
    in its own session/transaction (simulating ten different in-flight
    HTTP requests) -- all must converge on exactly one `Company` row."""

    async def _resolve() -> uuid.UUID:
        async with async_session_factory() as db:
            repo = CompanyRepository(db)
            company = await repo.get_or_create_by_key(
                normalized_key="domain:racey.com", domain="racey.com", company_name="Racey Inc"
            )
            await db.commit()
            return company.id

    results = await asyncio.gather(*[_resolve() for _ in range(10)])

    assert len(set(results)) == 1


async def test_upsert_signal_creates_then_updates_in_place():
    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        company = await repo.get_or_create_by_key(
            normalized_key="domain:example.com", domain="example.com", company_name="Example"
        )
        await db.commit()

    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        first = await repo.upsert_signal(
            company_id=company.id,
            verification_status=CompanyVerificationStatus.INSUFFICIENT_EVIDENCE,
            domain_age_days=None,
            domain_registered_at=None,
            domain_age_check=ProviderCheckOutcome.TIMEOUT.value,
            website_reachable=None,
            website_reachability_check=ProviderCheckOutcome.TIMEOUT.value,
            email_domain_match=None,
            evidence_ratio=0.0,
            last_checked_at=datetime.now(UTC),
        )
        await db.commit()

    assert first.verification_status == CompanyVerificationStatus.INSUFFICIENT_EVIDENCE

    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        second = await repo.upsert_signal(
            company_id=company.id,
            verification_status=CompanyVerificationStatus.FOUND,
            domain_age_days=1000,
            domain_registered_at=datetime.now(UTC) - timedelta(days=1000),
            domain_age_check=ProviderCheckOutcome.OK.value,
            website_reachable=True,
            website_reachability_check=ProviderCheckOutcome.OK.value,
            email_domain_match=True,
            evidence_ratio=1.0,
            last_checked_at=datetime.now(UTC),
        )
        await db.commit()

    # Same row, refreshed in place -- not a second row.
    assert second.id == first.id
    assert second.verification_status == CompanyVerificationStatus.FOUND
    assert second.domain_age_days == 1000

    async with async_session_factory() as db:
        stored = await CompanyRepository(db).get_signal(company.id)
    assert stored is not None
    assert stored.verification_status == CompanyVerificationStatus.FOUND


async def test_set_email_domain_match_only_touches_that_field():
    async with async_session_factory() as db:
        repo = CompanyRepository(db)
        company = await repo.get_or_create_by_key(
            normalized_key="domain:match.com", domain="match.com", company_name="Match Co"
        )
        await repo.upsert_signal(
            company_id=company.id,
            verification_status=CompanyVerificationStatus.FOUND,
            domain_age_days=42,
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
        await CompanyRepository(db).set_email_domain_match(company_id=company.id, matches=True)
        await db.commit()

    async with async_session_factory() as db:
        signal = await CompanyRepository(db).get_signal(company.id)

    assert signal is not None
    assert signal.email_domain_match is True
    # Untouched by the targeted update.
    assert signal.domain_age_days == 42
    assert signal.verification_status == CompanyVerificationStatus.FOUND


async def test_set_email_domain_match_is_a_noop_when_no_signal_row_exists():
    async with async_session_factory() as db:
        company = await CompanyRepository(db).get_or_create_by_key(
            normalized_key="domain:nosignal.com", domain="nosignal.com", company_name=None
        )
        await db.commit()

    async with async_session_factory() as db:
        await CompanyRepository(db).set_email_domain_match(company_id=company.id, matches=True)
        await db.commit()

    async with async_session_factory() as db:
        signal = await CompanyRepository(db).get_signal(company.id)
    assert signal is None
