"""Structured private report endpoints (M8: Structured Reporting + Reuse
Features).

Reports are private in this milestone -- there is no listing endpoint
for anyone else's reports, and no `report_id` is ever accepted from an
unauthenticated or cross-user context (M8 §10/§15). `PATCH
/reports/{id}/status` is the "internal tooling" hook the roadmap
explicitly allows in place of a moderator UI (M8 §5) -- gated by the
existing RBAC scaffold (`require_roles`), not a new mechanism.

`GET /reports/{id}` (full detail) is Pro-gated; `GET /reports/mine`
(basic list) and `POST /reports` are available to every plan -- see
`schemas/report.py` for which fields "basic" vs "detailed" means.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.auth.dependencies import CurrentUser, require_roles
from offerleaks.core.db import get_db_session
from offerleaks.core.rate_limit import rate_limit
from offerleaks.models.plan import PRO_PLAN_KEY
from offerleaks.models.user import Role
from offerleaks.schemas.report import (
    ReportCreateRequest,
    ReportDetailResponse,
    ReportListResponse,
    ReportStatusUpdateRequest,
    ReportSummaryResponse,
)
from offerleaks.services.entitlement_service import EntitlementService
from offerleaks.services.report_service import (
    InvalidStatusTransitionError,
    ReportNotFoundError,
    ReportService,
    ReportSubmission,
    ReportValidationError,
)

router = APIRouter(prefix="/reports", tags=["reports"])

# Reports are free-form user-authored text landing in the DB -- rate
# limit submission the same way upload is rate limited (§0.11), just
# lighter since this is a plain form post, not a provider-cost-bearing
# operation.
_submit_rate_limit = rate_limit(
    key="report_submit", max_attempts=10, window_seconds=300, per_user=True
)

_MAX_LIST_LIMIT = 50
_DEFAULT_LIST_LIMIT = 20


@router.post("", response_model=ReportSummaryResponse, status_code=status.HTTP_201_CREATED)
async def submit_report(
    payload: ReportCreateRequest,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[None, Depends(_submit_rate_limit)],
) -> ReportSummaryResponse:
    service = ReportService(db)
    submission = ReportSubmission(
        target_type=payload.target_type,
        reasons=payload.reasons,
        description=payload.description,
        company_id=payload.company_id,
        analysis_id=payload.analysis_id,
        target_detail=payload.target_detail,
    )
    try:
        report = await service.submit_report(user=current_user, submission=submission)
    except ReportValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    return ReportSummaryResponse.model_validate(report)


@router.get("/mine", response_model=ReportListResponse)
async def list_my_reports(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=_MAX_LIST_LIMIT)] = _DEFAULT_LIST_LIMIT,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ReportListResponse:
    service = ReportService(db)
    reports, total = await service.list_my_reports(user=current_user, limit=limit, offset=offset)
    return ReportListResponse(
        items=[ReportSummaryResponse.model_validate(r) for r in reports],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/{report_id}", response_model=ReportDetailResponse)
async def get_report_detail(
    report_id: uuid.UUID,
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> ReportDetailResponse:
    """Full report detail -- Pro-gated (M8 §"Billing": "detailed reports
    gated to Pro"). Ownership is checked *before* the plan check would
    even matter: a Free user gets the same 404 a non-owner would for a
    report that isn't theirs, never a 402 that would confirm a report
    they don't own exists.
    """
    service = ReportService(db)
    try:
        report = await service.get_owned_report(user=current_user, report_id=report_id)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found"
        ) from exc

    plan_resolution = await EntitlementService(db).resolve_plan(current_user.id)
    if plan_resolution.plan.key != PRO_PLAN_KEY:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Detailed report view is a Pro feature. Upgrade to Pro to see full detail.",
        )

    return ReportDetailResponse.model_validate(report)


@router.patch("/{report_id}/status", response_model=ReportDetailResponse)
async def update_report_status(
    report_id: uuid.UUID,
    payload: ReportStatusUpdateRequest,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    _: Annotated[object, Depends(require_roles(Role.ADMIN, Role.MODERATOR))],
) -> ReportDetailResponse:
    """Internal-tooling status transition (M8 §5: founder/internal review,
    not a public or moderator-UI surface) -- reuses the existing RBAC
    scaffold rather than a bespoke mechanism. Not reachable by a plain
    `Role.USER`, including the reporting user themselves.
    """
    service = ReportService(db)
    try:
        report = await service.transition_status(report_id=report_id, to_status=payload.status)
    except ReportNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Report not found"
        ) from exc
    except InvalidStatusTransitionError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    return ReportDetailResponse.model_validate(report)
