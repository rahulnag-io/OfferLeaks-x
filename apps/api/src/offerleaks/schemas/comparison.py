"""Request/response schemas for `GET /comparison` (M8, Pro-gated)."""

import uuid

from pydantic import BaseModel


class OfferComparisonItemResponse(BaseModel):
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


class OfferComparisonResponse(BaseModel):
    left: OfferComparisonItemResponse
    right: OfferComparisonItemResponse
