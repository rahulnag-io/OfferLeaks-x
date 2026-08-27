"""Personal scam analytics (M8: Structured Reporting + Reuse Features).

Pure query-layer feature over existing authoritative tables (`Analysis`,
`Verdict`, `Report`) -- no new schema, no AI, no application-side
aggregation over full history (M8 §"Personal scam analytics": "use
efficient database aggregation rather than loading excessive history
into application memory"). Every query below is scoped to `user_id`
inside the `WHERE`/`JOIN` itself, not filtered after the fact in Python,
so there is no code path where another user's rows could leak into the
result (M8 §15).

Risk-band thresholds (`_HIGH_RISK_THRESHOLD`/`_MEDIUM_RISK_THRESHOLD`)
intentionally match the bands `services/rules_engine.py::
recommended_actions_for` already uses for the exact same `risk_score`
scale, so "how many of my offers were high risk" means the same thing
here as it does on the verdict page itself.

All personal statistics here are free-tier (M8 §"Billing": "basic
personal stats free... good free-tier retention") -- this service has no
entitlement gating at all; `api/routers/analytics.py` calls it
unconditionally for any authenticated user.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.analysis import Analysis, Verdict
from offerleaks.models.report import Report

_HIGH_RISK_THRESHOLD = 70
_MEDIUM_RISK_THRESHOLD = 35


@dataclass(frozen=True, slots=True)
class PersonalAnalytics:
    total_analyses: int
    completed_analyses: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    average_risk_score: float | None
    distinct_companies_checked: int
    reports_submitted: int


class AnalyticsService:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_personal_stats(self, user_id: uuid.UUID) -> PersonalAnalytics:
        risk_band = case(
            (Verdict.risk_score >= _HIGH_RISK_THRESHOLD, "high"),
            (Verdict.risk_score >= _MEDIUM_RISK_THRESHOLD, "medium"),
            else_="low",
        )

        verdict_stmt = (
            select(
                func.count().label("completed_count"),
                func.avg(Verdict.risk_score).label("avg_risk"),
                func.count().filter(risk_band == "high").label("high_count"),
                func.count().filter(risk_band == "medium").label("medium_count"),
                func.count().filter(risk_band == "low").label("low_count"),
            )
            .select_from(Verdict)
            .join(Analysis, Analysis.id == Verdict.analysis_id)
            .where(Analysis.user_id == user_id)
        )
        verdict_row = (await self._db.execute(verdict_stmt)).one()

        total_stmt = select(func.count()).select_from(Analysis).where(Analysis.user_id == user_id)
        total_analyses = (await self._db.execute(total_stmt)).scalar_one()

        companies_stmt = (
            select(func.count(func.distinct(Analysis.company_id)))
            .select_from(Analysis)
            .where(Analysis.user_id == user_id, Analysis.company_id.is_not(None))
        )
        distinct_companies = (await self._db.execute(companies_stmt)).scalar_one()

        reports_stmt = (
            select(func.count()).select_from(Report).where(Report.user_id == user_id)
        )
        reports_submitted = (await self._db.execute(reports_stmt)).scalar_one()

        avg_risk = float(verdict_row.avg_risk) if verdict_row.avg_risk is not None else None

        return PersonalAnalytics(
            total_analyses=total_analyses,
            completed_analyses=verdict_row.completed_count or 0,
            high_risk_count=verdict_row.high_count or 0,
            medium_risk_count=verdict_row.medium_count or 0,
            low_risk_count=verdict_row.low_count or 0,
            average_risk_score=avg_risk,
            distinct_companies_checked=distinct_companies or 0,
            reports_submitted=reports_submitted or 0,
        )
