"""Tests for Version 4's credit refund behavior in the worker.

Companion to `test_analysis_worker.py`. Builds its own user+analysis+charge
fixture (rather than reusing `_create_user_and_pending_analysis`, which
deliberately has no credit balance) so refund amounts are observable.
"""

import uuid

import pytest

from offerleaks import worker
from offerleaks.core.db import async_session_factory
from offerleaks.models.analysis import AnalysisStatus
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.services.credit_service import CreditService

from .fakes import FakeAIProvider, FakeOCRProvider, FakeStorageProvider

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


async def _create_charged_user_and_analysis(
    *, storage: FakeStorageProvider
) -> tuple[uuid.UUID, uuid.UUID]:
    """Creates a user with a granted+charged balance and a PENDING
    analysis, mirroring what `AnalysisService.create_analysis` does in one
    transaction -- so refund tests observe a real charge being undone."""
    async with async_session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
        db.add(user)
        await db.flush()

        credits = CreditService(db)
        await credits.grant_initial_credits(user.id)
        await db.commit()

    async with async_session_factory() as db:
        storage_key = f"analyses/{user.id}/{uuid.uuid4()}/offer.pdf"
        storage.objects[storage_key] = PDF_BYTES

        repo = AnalysisRepository(db)
        analysis = await repo.create(
            user_id=user.id,
            file_storage_key=storage_key,
            file_name="offer.pdf",
            file_mime_type="application/pdf",
            file_size_bytes=len(PDF_BYTES),
            prompt_version="offer_letter_v1",
        )
        credits = CreditService(db)
        await credits.charge_for_analysis(user_id=user.id, analysis_id=analysis.id)
        await db.commit()
        return user.id, analysis.id


async def _get_balance(user_id: uuid.UUID) -> int:
    async with async_session_factory() as db:
        return await CreditService(db).get_balance(user_id)


@pytest.fixture
def storage() -> FakeStorageProvider:
    return FakeStorageProvider()


async def test_ocr_permanent_failure_refunds_credits(monkeypatch, storage) -> None:
    user_id, analysis_id = await _create_charged_user_and_analysis(storage=storage)
    balance_after_charge = await _get_balance(user_id)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider(permanent_error=True))
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).get_by_id(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.FAILED

    balance_after_failure = await _get_balance(user_id)
    assert balance_after_failure == balance_after_charge + 1  # refunded


async def test_storage_download_failure_refunds_credits(monkeypatch, storage) -> None:
    user_id, analysis_id = await _create_charged_user_and_analysis(storage=storage)
    balance_after_charge = await _get_balance(user_id)
    storage.objects.clear()  # simulate the object going missing

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    balance_after_failure = await _get_balance(user_id)
    assert balance_after_failure == balance_after_charge + 1


async def test_ai_failure_routed_to_manual_review_does_not_refund(monkeypatch, storage) -> None:
    """NEEDS_MANUAL_REVIEW means no automatic verdict was produced -- the
    user didn't get what their credit paid for, so it's refunded, same as
    the FAILED paths."""
    user_id, analysis_id = await _create_charged_user_and_analysis(storage=storage)
    balance_after_charge = await _get_balance(user_id)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(
        worker, "get_ai_provider", lambda: FakeAIProvider(always_fails=True, transient=True)
    )

    await worker._process_analysis(analysis_id)

    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).get_by_id(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.NEEDS_MANUAL_REVIEW

    balance_after = await _get_balance(user_id)
    assert balance_after == balance_after_charge + 1  # refunded


async def test_successful_analysis_does_not_refund(monkeypatch, storage) -> None:
    user_id, analysis_id = await _create_charged_user_and_analysis(storage=storage)
    balance_after_charge = await _get_balance(user_id)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    balance_after = await _get_balance(user_id)
    assert balance_after == balance_after_charge


async def test_redelivered_job_on_completed_analysis_does_not_double_refund(
    monkeypatch, storage
) -> None:
    """A duplicate/redelivered RQ job for an analysis that already reached
    COMPLETE must be a no-op -- specifically must NOT trigger a refund."""
    user_id, analysis_id = await _create_charged_user_and_analysis(storage=storage)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)
    balance_after_first_run = await _get_balance(user_id)

    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).get_by_id(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.COMPLETE

    # Redelivery: run the same job again against the now-COMPLETE analysis.
    await worker._process_analysis(analysis_id)

    balance_after_redelivery = await _get_balance(user_id)
    assert balance_after_redelivery == balance_after_first_run

    async with async_session_factory() as db:
        verdict = await AnalysisRepository(db).get_verdict(analysis_id)
    assert verdict is not None  # still exactly one verdict, no crash on duplicate insert


async def test_failed_job_retry_refunds_credits_exactly_once(monkeypatch, storage) -> None:
    """Simulates a worker retry after an unexpected crash: `_mark_failed_generic`
    runs, then a redelivered job also reaches the terminal-state guard.
    The refund must happen exactly once either way."""
    user_id, analysis_id = await _create_charged_user_and_analysis(storage=storage)
    balance_after_charge = await _get_balance(user_id)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider(permanent_error=True))
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)
    await worker._mark_failed_generic(analysis_id)  # e.g. a supervisor re-running cleanup

    balance_after = await _get_balance(user_id)
    assert balance_after == balance_after_charge + 1  # refunded once, not twice
