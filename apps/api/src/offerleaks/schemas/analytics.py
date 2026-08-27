"""Response schema for `GET /analytics/me` (M8). Free for every plan --
see `services/analytics_service.py` module docstring."""

from pydantic import BaseModel


class PersonalAnalyticsResponse(BaseModel):
    total_analyses: int
    completed_analyses: int
    high_risk_count: int
    medium_risk_count: int
    low_risk_count: int
    average_risk_score: float | None
    distinct_companies_checked: int
    reports_submitted: int
