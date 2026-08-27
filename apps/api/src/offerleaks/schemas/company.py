"""Response schemas for M7's company profile (attached to
`AnalysisResponse` -- there is no standalone `/companies` endpoint,
per M7's scope: company data is only ever surfaced in the context of an
analysis's verdict page).

Split into a basic, always-visible shape and an `advanced` sub-object
that is `None` for a non-Pro user -- gating is applied server-side when
this schema is built (`api/routers/analyses.py`), never left to the
frontend to hide/show (M7 §12: "do not rely on frontend gating alone").
"""

from datetime import datetime

from pydantic import BaseModel

from offerleaks.models.company import CompanyVerificationStatus


class CompanyAdvancedSignals(BaseModel):
    """Pro-only detail. Every field is nullable on its own terms (see
    `models/company.py`) -- `None` here always means "insufficient
    evidence for this specific signal," never "no" by default."""

    domain_age_days: int | None
    website_reachable: bool | None
    email_domain_match: bool | None


class CompanyProfileResponse(BaseModel):
    company_name: str | None
    domain: str | None
    verification_status: CompanyVerificationStatus
    last_checked_at: datetime
    # `None` for a Free user (gated out server-side); populated for Pro.
    advanced: CompanyAdvancedSignals | None = None
