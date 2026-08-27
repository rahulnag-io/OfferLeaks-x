"""Request/response schemas for the `/analyses` router."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict

from offerleaks.models.analysis import AnalysisStatus
from offerleaks.schemas.ai import RedFlag
from offerleaks.schemas.company import CompanyProfileResponse
from offerleaks.schemas.patterns import MatchedPattern


class VerdictResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    risk_score: int
    red_flags: list[RedFlag]
    reasoning: str
    confidence: float
    created_at: datetime
    # --- M6: Trust Verdict + Monetization Foundation ---
    matched_patterns: list[MatchedPattern] = []
    recommended_actions: list[str] = []
    evidence_coverage: float = 0.0


class AnalysisResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    status: AnalysisStatus
    file_name: str
    prompt_version: str
    error_message: str | None
    created_at: datetime
    updated_at: datetime
    verdict: VerdictResponse | None = None
    # Version 5: dashboard/history fields. `source_analysis_id` is set
    # only for a re-check (points at the analysis it re-ran). `credit_cost`
    # is what was actually charged for *this* analysis row -- every
    # analysis has a CONSUME ledger row except a free re-check (see
    # `AnalysisService.recheck_analysis`), so an analysis with no CONSUME
    # row is reported as costing 0, not left ambiguous.
    source_analysis_id: uuid.UUID | None = None
    credit_cost: int = 0
    # Whether the credit charged for this analysis was later given back
    # (worker-side failure/manual-review routing, or the stuck-analysis
    # reconciliation sweep -- see `offerleaks/reconciliation.py`).
    # Ledger-derived (`CreditRepository.get_refunded_analysis_ids`), not a
    # stored column -- the ledger stays the single source of truth for
    # "was this refunded," this is just a display-time read of it.
    credit_refunded: bool = False
    # M7: the shared company profile resolved for this analysis's sender
    # domain/company name, if any. `None` whenever nothing was resolvable
    # (honest "unable to verify," not an error) -- see
    # `api/routers/analyses.py::_build_company_response`.
    company: CompanyProfileResponse | None = None


class AnalysisListResponse(BaseModel):
    items: list[AnalysisResponse]
    total: int
    limit: int
    offset: int
