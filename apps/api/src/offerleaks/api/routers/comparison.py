"""Two-offer comparison endpoint (M8, Pro-gated).

Backend entitlement enforcement is authoritative here, same posture as
every other Pro-gated check in the codebase (`_build_company_response`'s
`advanced` gating, `EntitlementService.assert_within_monthly_quota`):
the plan is resolved server-side from DB subscription state, never from
a request parameter, header, or client-controlled entitlement claim.
"""

import dataclasses
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.auth.dependencies import CurrentUser
from offerleaks.core.db import get_db_session
from offerleaks.core.redis import get_redis
from offerleaks.models.plan import PRO_PLAN_KEY
from offerleaks.providers.factory import (
    get_domain_age_provider,
    get_website_reachability_provider,
)
from offerleaks.schemas.comparison import OfferComparisonItemResponse, OfferComparisonResponse
from offerleaks.services.company_profile_service import CompanyProfileService
from offerleaks.services.comparison_service import (
    ComparisonService,
    OfferNotFoundError,
    SameOfferComparisonError,
)
from offerleaks.services.entitlement_service import EntitlementService

router = APIRouter(prefix="/comparison", tags=["comparison"])


@router.get("", response_model=OfferComparisonResponse)
async def compare_offers(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
    analysis_id_a: uuid.UUID = Query(...),
    analysis_id_b: uuid.UUID = Query(...),
) -> OfferComparisonResponse:
    plan_resolution = await EntitlementService(db).resolve_plan(current_user.id)
    if plan_resolution.plan.key != PRO_PLAN_KEY:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail="Offer comparison is a Pro feature. Upgrade to Pro to compare offers.",
        )

    company_profiles = CompanyProfileService(
        db,
        await get_redis(),
        get_domain_age_provider(),
        get_website_reachability_provider(),
    )
    service = ComparisonService(db, company_profiles=company_profiles)
    try:
        comparison = await service.compare(
            user=current_user, analysis_id_a=analysis_id_a, analysis_id_b=analysis_id_b
        )
    except SameOfferComparisonError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot compare an offer with itself.",
        ) from exc
    except OfferNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="One or both offers were not found."
        ) from exc

    return OfferComparisonResponse(
        left=OfferComparisonItemResponse(**dataclasses.asdict(comparison.left)),
        right=OfferComparisonItemResponse(**dataclasses.asdict(comparison.right)),
    )
