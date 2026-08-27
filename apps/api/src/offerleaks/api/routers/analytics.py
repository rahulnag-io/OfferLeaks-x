"""Personal scam analytics endpoint (M8). Free for every plan -- no
entitlement check here at all, see `services/analytics_service.py`.
"""

from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.auth.dependencies import CurrentUser
from offerleaks.core.db import get_db_session
from offerleaks.schemas.analytics import PersonalAnalyticsResponse
from offerleaks.services.analytics_service import AnalyticsService

router = APIRouter(prefix="/analytics", tags=["analytics"])


@router.get("/me", response_model=PersonalAnalyticsResponse)
async def get_my_analytics(
    current_user: CurrentUser,
    db: Annotated[AsyncSession, Depends(get_db_session)],
) -> PersonalAnalyticsResponse:
    stats = await AnalyticsService(db).get_personal_stats(current_user.id)
    return PersonalAnalyticsResponse(
        total_analyses=stats.total_analyses,
        completed_analyses=stats.completed_analyses,
        high_risk_count=stats.high_risk_count,
        medium_risk_count=stats.medium_risk_count,
        low_risk_count=stats.low_risk_count,
        average_risk_score=stats.average_risk_score,
        distinct_companies_checked=stats.distinct_companies_checked,
        reports_submitted=stats.reports_submitted,
    )
