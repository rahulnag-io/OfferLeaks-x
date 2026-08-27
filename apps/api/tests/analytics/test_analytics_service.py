"""Tests for `AnalyticsService` against real Postgres and known fixture
data (M8). Verifies SQL-aggregation correctness, per-user scoping,
empty-history honesty, and that another user's history never leaks in.
"""

import uuid

from offerleaks.core.db import async_session_factory
from offerleaks.models.report import ReportReason, ReportTargetType
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.services.analytics_service import AnalyticsService
from offerleaks.services.report_service import ReportService, ReportSubmission


async def _create_user() -> User:
    async with async_session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
        db.add(user)
        await db.flush()
        await db.commit()
        await db.refresh(user)
        return user


async def _create_company(key: str) -> uuid.UUID:
    async with async_session_factory() as db:
        company = await CompanyRepository(db).get_or_create_by_key(
            normalized_key=key, domain=key.removeprefix("domain:"), company_name="Test Co"
        )
        await db.commit()
        return company.id


async def _create_analysis_with_verdict(
    user_id: uuid.UUID, *, risk_score: int, company_id: uuid.UUID | None = None
) -> uuid.UUID:
    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        analysis = await repo.create(
            user_id=user_id,
            file_storage_key=f"analyses/{user_id}/{uuid.uuid4()}/offer.pdf",
            file_name="offer.pdf",
            file_mime_type="application/pdf",
            file_size_bytes=100,
            prompt_version="offer_letter_v1",
        )
        if company_id is not None:
            analysis.company_id = company_id
            await db.flush()
        await repo.create_verdict(
            analysis_id=analysis.id,
            risk_score=risk_score,
            red_flags=[{"description": "test flag"}] if risk_score >= 70 else [],
            reasoning="test reasoning",
            confidence=0.9,
        )
        await db.commit()
        return analysis.id


async def test_empty_history_returns_honest_zero_state():
    user = await _create_user()
    async with async_session_factory() as db:
        stats = await AnalyticsService(db).get_personal_stats(user.id)

    assert stats.total_analyses == 0
    assert stats.completed_analyses == 0
    assert stats.high_risk_count == 0
    assert stats.medium_risk_count == 0
    assert stats.low_risk_count == 0
    assert stats.average_risk_score is None
    assert stats.distinct_companies_checked == 0
    assert stats.reports_submitted == 0


async def test_risk_band_counts_match_known_fixture_data():
    user = await _create_user()
    # 2 high (>=70), 1 medium (35-69), 1 low (<35)
    await _create_analysis_with_verdict(user.id, risk_score=90)
    await _create_analysis_with_verdict(user.id, risk_score=71)
    await _create_analysis_with_verdict(user.id, risk_score=50)
    await _create_analysis_with_verdict(user.id, risk_score=10)

    async with async_session_factory() as db:
        stats = await AnalyticsService(db).get_personal_stats(user.id)

    assert stats.total_analyses == 4
    assert stats.completed_analyses == 4
    assert stats.high_risk_count == 2
    assert stats.medium_risk_count == 1
    assert stats.low_risk_count == 1
    assert stats.average_risk_score == (90 + 71 + 50 + 10) / 4


async def test_total_analyses_includes_incomplete_analyses_without_a_verdict():
    user = await _create_user()
    async with async_session_factory() as db:
        # No verdict -- e.g. still processing.
        await AnalysisRepository(db).create(
            user_id=user.id,
            file_storage_key=f"analyses/{user.id}/{uuid.uuid4()}/offer.pdf",
            file_name="offer.pdf",
            file_mime_type="application/pdf",
            file_size_bytes=100,
            prompt_version="offer_letter_v1",
        )
        await db.commit()

    async with async_session_factory() as db:
        stats = await AnalyticsService(db).get_personal_stats(user.id)

    assert stats.total_analyses == 1
    assert stats.completed_analyses == 0
    assert stats.average_risk_score is None


async def test_distinct_companies_checked_deduplicates_repeat_uploads_for_the_same_company():
    user = await _create_user()
    company_id = await _create_company("domain:repeat-company.com")
    await _create_analysis_with_verdict(user.id, risk_score=80, company_id=company_id)
    await _create_analysis_with_verdict(user.id, risk_score=20, company_id=company_id)

    async with async_session_factory() as db:
        stats = await AnalyticsService(db).get_personal_stats(user.id)

    assert stats.distinct_companies_checked == 1


async def test_analytics_are_scoped_to_the_authenticated_user_only():
    user_a = await _create_user()
    user_b = await _create_user()
    await _create_analysis_with_verdict(user_a.id, risk_score=90)
    await _create_analysis_with_verdict(user_b.id, risk_score=90)
    await _create_analysis_with_verdict(user_b.id, risk_score=90)

    async with async_session_factory() as db:
        stats_a = await AnalyticsService(db).get_personal_stats(user_a.id)
        stats_b = await AnalyticsService(db).get_personal_stats(user_b.id)

    assert stats_a.total_analyses == 1
    assert stats_b.total_analyses == 2


async def test_reports_submitted_count_is_scoped_to_the_user():
    user_a = await _create_user()
    user_b = await _create_user()
    company_id = await _create_company("domain:analytics-reports.com")

    async with async_session_factory() as db:
        service = ReportService(db)
        await service.submit_report(
            user=user_a,
            submission=ReportSubmission(
                target_type=ReportTargetType.COMPANY,
                reasons=[ReportReason.OTHER],
                description="A sufficiently long description of the issue encountered.",
                company_id=company_id,
            ),
        )

    async with async_session_factory() as db:
        stats_a = await AnalyticsService(db).get_personal_stats(user_a.id)
        stats_b = await AnalyticsService(db).get_personal_stats(user_b.id)

    assert stats_a.reports_submitted == 1
    assert stats_b.reports_submitted == 0
