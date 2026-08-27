"""Tests for `ComparisonService` against real Postgres and known fixture
data (M8). Verifies correctness against authoritative data, ownership
enforcement, and the same-offer / cross-user edge cases.
"""

import uuid

import pytest

from offerleaks.core.db import async_session_factory
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.services.comparison_service import (
    ComparisonService,
    OfferNotFoundError,
    SameOfferComparisonError,
)


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
            normalized_key=key, domain=key.removeprefix("domain:"), company_name="Comparison Co"
        )
        await db.commit()
        return company.id


async def _create_analysis_with_verdict(
    user_id: uuid.UUID,
    *,
    risk_score: int,
    file_name: str = "offer.pdf",
    company_id: uuid.UUID | None = None,
    with_verdict: bool = True,
) -> uuid.UUID:
    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        analysis = await repo.create(
            user_id=user_id,
            file_storage_key=f"analyses/{user_id}/{uuid.uuid4()}/{file_name}",
            file_name=file_name,
            file_mime_type="application/pdf",
            file_size_bytes=100,
            prompt_version="offer_letter_v1",
        )
        if company_id is not None:
            analysis.company_id = company_id
            await db.flush()
        if with_verdict:
            await repo.create_verdict(
                analysis_id=analysis.id,
                risk_score=risk_score,
                red_flags=[{"description": "flag one"}, {"description": "flag two"}],
                reasoning="test reasoning",
                confidence=0.75,
                matched_patterns=[{"key": "test_pattern"}],
                recommended_actions=["Verify the company independently."],
            )
        await db.commit()
        return analysis.id


async def test_compare_two_owned_offers_returns_authoritative_values():
    user = await _create_user()
    company_id = await _create_company("domain:compare-a.com")
    analysis_a = await _create_analysis_with_verdict(
        user.id, risk_score=85, file_name="offer_a.pdf", company_id=company_id
    )
    analysis_b = await _create_analysis_with_verdict(
        user.id, risk_score=20, file_name="offer_b.pdf"
    )

    async with async_session_factory() as db:
        comparison = await ComparisonService(db).compare(
            user=user, analysis_id_a=analysis_a, analysis_id_b=analysis_b
        )

    assert comparison.left.analysis_id == analysis_a
    assert comparison.left.risk_score == 85
    assert comparison.left.company_name == "Comparison Co"
    assert comparison.left.red_flag_count == 2
    assert comparison.left.matched_pattern_count == 1

    assert comparison.right.analysis_id == analysis_b
    assert comparison.right.risk_score == 20
    assert comparison.right.company_name is None


async def test_reversed_offer_order_is_logically_consistent():
    user = await _create_user()
    analysis_a = await _create_analysis_with_verdict(user.id, risk_score=85, file_name="a.pdf")
    analysis_b = await _create_analysis_with_verdict(user.id, risk_score=20, file_name="b.pdf")

    async with async_session_factory() as db:
        forward = await ComparisonService(db).compare(
            user=user, analysis_id_a=analysis_a, analysis_id_b=analysis_b
        )
    async with async_session_factory() as db:
        reversed_ = await ComparisonService(db).compare(
            user=user, analysis_id_a=analysis_b, analysis_id_b=analysis_a
        )

    assert forward.left.analysis_id == reversed_.right.analysis_id
    assert forward.right.analysis_id == reversed_.left.analysis_id
    assert forward.left.risk_score == reversed_.right.risk_score


async def test_missing_verdict_is_handled_consistently_not_fabricated():
    user = await _create_user()
    analysis_a = await _create_analysis_with_verdict(
        user.id, risk_score=0, file_name="pending.pdf", with_verdict=False
    )
    analysis_b = await _create_analysis_with_verdict(user.id, risk_score=40, file_name="done.pdf")

    async with async_session_factory() as db:
        comparison = await ComparisonService(db).compare(
            user=user, analysis_id_a=analysis_a, analysis_id_b=analysis_b
        )

    assert comparison.left.risk_score is None
    assert comparison.left.red_flag_count is None
    assert comparison.left.recommended_actions == []
    assert comparison.right.risk_score == 40


async def test_comparing_an_offer_with_itself_is_rejected():
    user = await _create_user()
    analysis_id = await _create_analysis_with_verdict(user.id, risk_score=50)

    async with async_session_factory() as db:
        with pytest.raises(SameOfferComparisonError):
            await ComparisonService(db).compare(
                user=user, analysis_id_a=analysis_id, analysis_id_b=analysis_id
            )


async def test_comparison_rejects_another_users_offer():
    owner = await _create_user()
    attacker = await _create_user()
    owner_analysis = await _create_analysis_with_verdict(owner.id, risk_score=50)
    attacker_analysis = await _create_analysis_with_verdict(attacker.id, risk_score=10)

    async with async_session_factory() as db:
        with pytest.raises(OfferNotFoundError):
            await ComparisonService(db).compare(
                user=attacker, analysis_id_a=owner_analysis, analysis_id_b=attacker_analysis
            )


async def test_comparison_rejects_a_nonexistent_offer():
    user = await _create_user()
    real_analysis = await _create_analysis_with_verdict(user.id, risk_score=50)

    async with async_session_factory() as db:
        with pytest.raises(OfferNotFoundError):
            await ComparisonService(db).compare(
                user=user, analysis_id_a=real_analysis, analysis_id_b=uuid.uuid4()
            )
