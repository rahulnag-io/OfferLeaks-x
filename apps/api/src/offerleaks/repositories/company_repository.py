"""Data access for `Company`/`CompanySignal` (M7: Company Signal &
Reputation).

`get_or_create_by_key` is the one place a new `Company` row can be born,
using Postgres's `ON CONFLICT DO NOTHING` + a follow-up `SELECT` so two
concurrent requests resolving the same brand-new company race safely --
neither errors, and both end up with the same row (M7 concurrency
requirement: "normalization collisions... do not produce duplicate
company records").
"""

import uuid
from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.company import Company, CompanySignal, CompanyVerificationStatus


class CompanyRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_by_key(self, normalized_key: str) -> Company | None:
        result = await self._db.execute(
            select(Company).where(Company.normalized_key == normalized_key)
        )
        return result.scalar_one_or_none()

    async def get_by_id(self, company_id: uuid.UUID) -> Company | None:
        result = await self._db.execute(select(Company).where(Company.id == company_id))
        return result.scalar_one_or_none()

    async def get_or_create_by_key(
        self, *, normalized_key: str, domain: str | None, company_name: str | None
    ) -> Company:
        """Idempotent under concurrency: an `INSERT ... ON CONFLICT
        (normalized_key) DO NOTHING`, then a plain read. If the insert
        won the race, the row it just committed is read back; if it
        lost, the concurrent winner's row is read instead -- either way
        the caller gets a single, real `Company` row, never a duplicate
        and never an unhandled unique-violation.
        """
        stmt = (
            pg_insert(Company)
            .values(normalized_key=normalized_key, domain=domain, company_name=company_name)
            .on_conflict_do_nothing(index_elements=[Company.normalized_key])
        )
        await self._db.execute(stmt)
        await self._db.flush()

        existing = await self.get_by_key(normalized_key)
        assert existing is not None  # the row above (ours or a concurrent winner's) must exist
        return existing

    async def upgrade_name_only_company(
        self, *, company_id: uuid.UUID, normalized_key: str, domain: str
    ) -> Company:
        """Migrates a company that was first resolved by name alone (no
        domain evidence yet) onto a domain-based identity, *in place*,
        once a later analysis supplies a domain -- rather than creating a
        second, disconnected `Company` row that the name-based one would
        never merge into (audit finding: domain-vs-name resolution
        ordering could otherwise silently split one real company into
        two permanently-separate cached profiles).

        Guarded by `WHERE domain IS NULL` so this only ever fires on a
        genuinely name-only row -- it will never silently overwrite a
        domain a company already has. Callers should only ever call this
        when they've already confirmed the target row has `domain is
        None`; the guard is a belt-and-suspenders safety net, not the
        primary check. Three possible outcomes, all returning a single,
        real `Company` rather than ever raising or duplicating:
        1. The update applied (row genuinely was name-only) -- returns
           the now-upgraded row.
        2. A concurrent request already performed this same upgrade, or
           an unrelated analysis already created a `Company` under this
           exact domain key first -- the unique constraint is violated;
           not an error, just a lost race, so we roll back and return
           the winner's row instead.
        3. The guard didn't match because this row already had its own,
           different domain (not a race, just a legitimate no-op) --
           returns the original, unmodified row.
        """
        try:
            await self._db.execute(
                update(Company)
                .where(Company.id == company_id, Company.domain.is_(None))
                .values(normalized_key=normalized_key, domain=domain)
            )
            await self._db.flush()
        except IntegrityError:
            await self._db.rollback()
            winner = await self.get_by_key(normalized_key)
            if winner is not None:
                return winner
            raise

        updated = await self.get_by_id(company_id)
        assert updated is not None  # the row we started with must still exist

        if updated.normalized_key == normalized_key:
            return updated  # the upgrade succeeded

        winner = await self.get_by_key(normalized_key)
        if winner is not None:
            # Someone else already upgraded/created a company under this
            # exact key first -- that's the real winner, not us.
            return winner

        # Neither: the `WHERE domain IS NULL` guard simply didn't match
        # (this company already had its own, different domain) -- not a
        # race, just a legitimate no-op. Return the original, unmodified
        # row rather than asserting.
        return updated

    async def get_signal(self, company_id: uuid.UUID) -> CompanySignal | None:
        result = await self._db.execute(
            select(CompanySignal).where(CompanySignal.company_id == company_id)
        )
        return result.scalar_one_or_none()

    async def upsert_signal(
        self,
        *,
        company_id: uuid.UUID,
        verification_status: CompanyVerificationStatus,
        domain_age_days: int | None,
        domain_registered_at: datetime | None,
        domain_age_check: str,
        website_reachable: bool | None,
        website_reachability_check: str,
        email_domain_match: bool | None,
        evidence_ratio: float,
        last_checked_at: datetime,
    ) -> CompanySignal:
        """Writes (or refreshes, in place) the single signal row for
        `company_id`. `ON CONFLICT (company_id) DO UPDATE` so a
        concurrent refresh for the same company is a safe last-write-wins
        update rather than a unique-constraint error -- there is
        deliberately no history table (M7: reputation trend history is
        explicitly deferred to M9), so overwriting is the correct
        semantics, not a shortcut.
        """
        stmt = (
            pg_insert(CompanySignal)
            .values(
                company_id=company_id,
                verification_status=verification_status,
                domain_age_days=domain_age_days,
                domain_registered_at=domain_registered_at,
                domain_age_check=domain_age_check,
                website_reachable=website_reachable,
                website_reachability_check=website_reachability_check,
                email_domain_match=email_domain_match,
                evidence_ratio=evidence_ratio,
                last_checked_at=last_checked_at,
            )
            .on_conflict_do_update(
                index_elements=[CompanySignal.company_id],
                set_={
                    "verification_status": verification_status,
                    "domain_age_days": domain_age_days,
                    "domain_registered_at": domain_registered_at,
                    "domain_age_check": domain_age_check,
                    "website_reachable": website_reachable,
                    "website_reachability_check": website_reachability_check,
                    "email_domain_match": email_domain_match,
                    "evidence_ratio": evidence_ratio,
                    "last_checked_at": last_checked_at,
                },
            )
        )
        await self._db.execute(stmt)
        await self._db.flush()

        signal = await self.get_signal(company_id)
        assert signal is not None
        return signal

    async def set_report_reputation_signal(
        self,
        *,
        company_id: uuid.UUID,
        verified_report_count: int,
        internal_reputation_score: int | None,
    ) -> None:
        """M8: updates only the report-derived internal reputation
        columns on the company's signal row, without touching the
        independently-computed M7 provider signals (domain age, website
        reachability, email-domain-match) -- same "update only what this
        caller owns" pattern as `set_email_domain_match` above.

        Every real, reportable company already has a placeholder signal
        row by construction (`CompanyProfileService.resolve_for_analysis`
        creates one the first time any company is ever resolved -- there
        is no other path to create a `Company`). This is still an
        `INSERT ... ON CONFLICT DO UPDATE` rather than a plain `UPDATE`,
        so a row is never silently skipped in the one scenario that
        invariant doesn't hold (e.g. a future code path or data-repair
        script that creates a `Company` directly) -- the alternative, a
        bare `UPDATE` that matches zero rows, would silently discard a
        report's reputation contribution with no error and no signal
        that anything went wrong, which is exactly the kind of "silent
        data loss" M8 §14 forbids.
        """
        stmt = (
            pg_insert(CompanySignal)
            .values(
                company_id=company_id,
                verified_report_count=verified_report_count,
                internal_reputation_score=internal_reputation_score,
            )
            .on_conflict_do_update(
                index_elements=[CompanySignal.company_id],
                set_={
                    "verified_report_count": verified_report_count,
                    "internal_reputation_score": internal_reputation_score,
                },
            )
        )
        await self._db.execute(stmt)
        await self._db.flush()

    async def set_email_domain_match(self, *, company_id: uuid.UUID, matches: bool | None) -> None:
        """Updates only `email_domain_match` on an *existing* signal row,
        without touching the other (independently, more expensively
        computed) signal fields. A no-op if the company has no signal row
        yet -- callers resolving a brand-new company must create the
        placeholder signal row themselves first (see
        `CompanyProfileService.resolve_for_analysis`), or this value is
        silently lost rather than merely deferred."""
        await self._db.execute(
            update(CompanySignal)
            .where(CompanySignal.company_id == company_id)
            .values(email_domain_match=matches)
        )
        await self._db.flush()
