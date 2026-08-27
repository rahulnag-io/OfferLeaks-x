"""Request/response schemas for the `/reports` router (M8)."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from offerleaks.models.report import ReportReason, ReportStatus, ReportTargetType


class ReportCreateRequest(BaseModel):
    target_type: ReportTargetType
    reasons: list[ReportReason] = Field(min_length=1, max_length=6)
    description: str = Field(min_length=10, max_length=5000)
    # Required for target_type=COMPANY, ignored for target_type=OFFER
    # (the offer's own resolved company is used instead -- see
    # `ReportService.submit_report`).
    company_id: uuid.UUID | None = None
    # Required for target_type=OFFER.
    analysis_id: uuid.UUID | None = None
    # Required for target_type=RECRUITER/WEBSITE (name/URL/email).
    target_detail: str | None = Field(default=None, max_length=500)


class ReportSummaryResponse(BaseModel):
    """Basic shape -- visible to the owning user regardless of plan (M8
    §"Billing": only *detailed* reports are Pro-gated, not the fact that
    a report exists or its status)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    target_type: ReportTargetType
    status: ReportStatus
    is_duplicate: bool
    created_at: datetime


class ReportDetailResponse(ReportSummaryResponse):
    """Full shape -- Pro-gated (M8 §"Billing": "detailed reports...
    gated to Pro"). Never returned for a report the caller doesn't own
    (`ReportService.get_owned_report`)."""

    company_id: uuid.UUID | None
    analysis_id: uuid.UUID | None
    target_detail: str | None
    reasons: list[ReportReason]
    description: str
    updated_at: datetime


class ReportListResponse(BaseModel):
    items: list[ReportSummaryResponse]
    total: int
    limit: int
    offset: int


class ReportStatusUpdateRequest(BaseModel):
    status: ReportStatus
