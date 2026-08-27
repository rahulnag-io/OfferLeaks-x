"""Two-offer, side-by-side comparison (M8: Structured Reporting + Reuse
Features).

A "saved offer" is simply a user's own `Analysis` -- the roadmap's
"comparison of 2 saved offers" maps directly onto the existing
upload/dashboard-history entity rather than introducing a second,
parallel notion of "saved" (M8 §8/§9: "no new schema is required for
comparison... a query-layer feature over existing tables"). This is the
smallest reasonable engineering decision: every uploaded offer letter is
already durably stored and owned by exactly one user, which is exactly
what "saved" means here.

No new scoring/analysis logic -- every field in `OfferComparisonItem` is
read directly off the existing `Analysis`/`Verdict`/`Company` rows
(M8 §"Offer comparison": "must not create a new scoring engine merely to
compare offers").
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.analysis import Analysis, Verdict
from offerleaks.models.company import Company
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.services.company_profile_service import CompanyProfileService


class ComparisonServiceError(Exception):
    """Base class for all comparison-service failures. Routers map this to 4xx."""


class OfferNotFoundError(ComparisonServiceError):
    """Raised for either a nonexistent analysis or one not owned by the
    requesting user -- deliberately not distinguished (same no-enumeration
    principle as `AnalysisService.get_owned_analysis`)."""


class SameOfferComparisonError(ComparisonServiceError):
    """Comparing an offer against itself carries no information -- the
    smallest reasonable UX/API contract for M8 §"duplicate selection of
    the same offer" is to reject it outright with a clear error, rather
    than silently returning two identical columns."""


@dataclass(frozen=True, slots=True)
class OfferComparisonItem:
    analysis_id: uuid.UUID
    file_name: str
    status: str
    created_at: str
    company_name: str | None
    company_domain: str | None
    company_verification_status: str | None
    risk_score: int | None
    confidence: float | None
    red_flag_count: int | None
    matched_pattern_count: int | None
    recommended_actions: list[str]


@dataclass(frozen=True, slots=True)
class OfferComparison:
    left: OfferComparisonItem
    right: OfferComparisonItem


class ComparisonService:
    def __init__(
        self,
        db: AsyncSession,
        *,
        company_profiles: CompanyProfileService | None = None,
    ) -> None:
        self._db = db
        self._analyses = AnalysisRepository(db)
        self._companies = CompanyRepository(db)
        # Reuses M7's own cache-aware read (`CompanyProfileService.
        # get_profile`) for verification status rather than re-reading
        # `CompanySignal` directly -- a second read path for the same
        # data would be exactly the "competing implementation of an
        # existing responsibility" M8 forbids (§8). Optional: `None` is
        # a valid, fully-functional configuration (verification status
        # simply reads back `None` for both offers) so tests/callers that
        # don't need it never have to wire up Redis/providers just to
        # compare two offers.
        self._company_profiles = company_profiles

    async def compare(
        self, *, user: User, analysis_id_a: uuid.UUID, analysis_id_b: uuid.UUID
    ) -> OfferComparison:
        if analysis_id_a == analysis_id_b:
            raise SameOfferComparisonError

        analysis_a = await self._analyses.get_owned_by(analysis_id_a, user.id)
        analysis_b = await self._analyses.get_owned_by(analysis_id_b, user.id)
        if analysis_a is None or analysis_b is None:
            # Ownership is checked independently for each id -- neither
            # "the other one is fine" nor which specific id failed is
            # ever revealed to the caller, same as every other owned-
            # resource lookup in the codebase.
            raise OfferNotFoundError

        verdicts = await self._analyses.get_verdicts_for([analysis_a.id, analysis_b.id])
        companies = await self._load_companies([analysis_a, analysis_b])
        verification_statuses = await self._load_verification_statuses(companies)

        return OfferComparison(
            left=self._to_item(
                analysis_a, verdicts.get(analysis_a.id), companies, verification_statuses
            ),
            right=self._to_item(
                analysis_b, verdicts.get(analysis_b.id), companies, verification_statuses
            ),
        )

    async def _load_companies(self, analyses: list[Analysis]) -> dict[uuid.UUID, Company]:
        companies: dict[uuid.UUID, Company] = {}
        for analysis in analyses:
            if analysis.company_id is None or analysis.company_id in companies:
                continue
            company = await self._companies.get_by_id(analysis.company_id)
            if company is not None:
                companies[analysis.company_id] = company
        return companies

    async def _load_verification_statuses(
        self, companies: dict[uuid.UUID, Company]
    ) -> dict[uuid.UUID, str]:
        if self._company_profiles is None:
            return {}
        statuses: dict[uuid.UUID, str] = {}
        for company_id, company in companies.items():
            # Read-only: deliberately does not call `ensure_fresh` here
            # -- comparison is a presentation feature over whatever is
            # already known (M8 §"Offer comparison": "must use existing
            # authoritative data"), triggering background refreshes is
            # the verdict page's job, not this one's.
            profile = await self._company_profiles.get_profile(company)
            if profile is not None:
                statuses[company_id] = profile.verification_status.value
        return statuses

    def _to_item(
        self,
        analysis: Analysis,
        verdict: Verdict | None,
        companies: dict[uuid.UUID, Company],
        verification_statuses: dict[uuid.UUID, str],
    ) -> OfferComparisonItem:
        company = companies.get(analysis.company_id) if analysis.company_id else None

        return OfferComparisonItem(
            analysis_id=analysis.id,
            file_name=analysis.file_name,
            status=analysis.status.value,
            created_at=analysis.created_at.isoformat(),
            company_name=company.company_name if company is not None else None,
            company_domain=company.domain if company is not None else None,
            company_verification_status=(
                verification_statuses.get(analysis.company_id)
                if analysis.company_id is not None
                else None
            ),
            risk_score=verdict.risk_score if verdict is not None else None,
            confidence=verdict.confidence if verdict is not None else None,
            red_flag_count=len(verdict.red_flags) if verdict is not None else None,
            matched_pattern_count=(
                len(verdict.matched_patterns) if verdict is not None else None
            ),
            recommended_actions=verdict.recommended_actions if verdict is not None else [],
        )
