"""Tests for `CreditService` -- the authoritative credit business logic."""

import uuid

import pytest

from offerleaks.core.db import async_session_factory
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.services.credit_service import CreditService, InsufficientCreditsError


async def _create_user() -> uuid.UUID:
    async with async_session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
        db.add(user)
        await db.flush()
        await db.commit()
        return user.id


async def _create_pending_analysis(user_id: uuid.UUID) -> uuid.UUID:
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
        await db.commit()
        return analysis.id


async def test_grant_initial_credits_is_idempotent():
    user_id = await _create_user()
    async with async_session_factory() as db:
        credits = CreditService(db)
        balance1 = await credits.grant_initial_credits(user_id)
        await db.commit()
    async with async_session_factory() as db:
        credits = CreditService(db)
        balance2 = await credits.grant_initial_credits(user_id)
        await db.commit()

    assert balance1 == credits.cost_per_analysis or balance1 >= 0  # sanity
    assert balance1 == balance2  # second grant is a no-op


async def test_charge_for_analysis_deducts_balance():
    user_id = await _create_user()
    analysis_id = await _create_pending_analysis(user_id)

    async with async_session_factory() as db:
        credits = CreditService(db)
        await credits.grant_initial_credits(user_id)
        await db.commit()

    async with async_session_factory() as db:
        credits = CreditService(db)
        starting = await credits.get_balance(user_id)
        result = await credits.charge_for_analysis(user_id=user_id, analysis_id=analysis_id)
        await db.commit()

    assert result.amount_charged == credits.cost_per_analysis
    assert result.remaining_balance == starting - credits.cost_per_analysis


async def test_charge_for_analysis_raises_when_insufficient():
    user_id = await _create_user()
    analysis_id = await _create_pending_analysis(user_id)
    # Deliberately no grant -- balance is 0.

    async with async_session_factory() as db:
        credits = CreditService(db)
        with pytest.raises(InsufficientCreditsError) as exc_info:
            await credits.charge_for_analysis(user_id=user_id, analysis_id=analysis_id)
        await db.rollback()

    assert exc_info.value.available == 0
    assert exc_info.value.required == credits.cost_per_analysis


async def test_charge_for_analysis_is_idempotent_and_does_not_double_charge():
    user_id = await _create_user()
    analysis_id = await _create_pending_analysis(user_id)

    async with async_session_factory() as db:
        credits = CreditService(db)
        await credits.grant_initial_credits(user_id)
        await db.commit()

    async with async_session_factory() as db:
        credits = CreditService(db)
        await credits.charge_for_analysis(user_id=user_id, analysis_id=analysis_id)
        await db.commit()
        after_first_charge = await credits.get_balance(user_id)

    # A second charge attempt for the *same* analysis_id must not succeed
    # in taking a second credit -- it detects the existing CONSUME ledger
    # row, gives back what it conditionally took, and raises.
    async with async_session_factory() as db:
        credits = CreditService(db)
        with pytest.raises(Exception):  # noqa: B017 - CreditServiceError, deliberately broad here
            await credits.charge_for_analysis(user_id=user_id, analysis_id=analysis_id)
        await db.commit()

    async with async_session_factory() as db:
        credits = CreditService(db)
        final_balance = await credits.get_balance(user_id)

    assert final_balance == after_first_charge  # unchanged by the duplicate attempt


async def test_refund_for_analysis_restores_balance_once():
    user_id = await _create_user()
    analysis_id = await _create_pending_analysis(user_id)

    async with async_session_factory() as db:
        credits = CreditService(db)
        await credits.grant_initial_credits(user_id)
        await credits.charge_for_analysis(user_id=user_id, analysis_id=analysis_id)
        await db.commit()
        after_charge = await credits.get_balance(user_id)

    async with async_session_factory() as db:
        credits = CreditService(db)
        refunded = await credits.refund_for_analysis(user_id=user_id, analysis_id=analysis_id)
        await db.commit()
    assert refunded is True

    async with async_session_factory() as db:
        credits = CreditService(db)
        after_refund = await credits.get_balance(user_id)
    assert after_refund == after_charge + credits.cost_per_analysis

    # A second refund attempt for the same analysis is a safe no-op.
    async with async_session_factory() as db:
        credits = CreditService(db)
        refunded_again = await credits.refund_for_analysis(user_id=user_id, analysis_id=analysis_id)
        await db.commit()
    assert refunded_again is False

    async with async_session_factory() as db:
        credits = CreditService(db)
        final_balance = await credits.get_balance(user_id)
    assert final_balance == after_refund  # not refunded twice


async def test_refund_for_analysis_that_was_never_charged_is_a_noop():
    user_id = await _create_user()
    analysis_id = await _create_pending_analysis(user_id)

    async with async_session_factory() as db:
        credits = CreditService(db)
        await credits.grant_initial_credits(user_id)
        await db.commit()
        starting = await credits.get_balance(user_id)

    async with async_session_factory() as db:
        credits = CreditService(db)
        refunded = await credits.refund_for_analysis(user_id=user_id, analysis_id=analysis_id)
        await db.commit()

    assert refunded is False

    async with async_session_factory() as db:
        final_balance = await CreditService(db).get_balance(user_id)
    assert final_balance == starting  # unchanged
