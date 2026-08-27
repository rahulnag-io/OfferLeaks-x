"""Tests for `offerleaks.worker._process_analysis` -- the OCR -> AI verdict
pipeline that runs in the background job (architecture.md §0.7/§0.8).

Runs against the real Postgres instance (via `_clean_state`, same as
every other test module) but with the external providers faked, for the
same reason as the endpoint tests: this is exactly the seam the
`OCRProvider`/`AIProvider`/`StorageProvider` interfaces exist to isolate.
"""

import uuid

import pytest

from offerleaks import worker
from offerleaks.core.db import async_session_factory
from offerleaks.models.analysis import AnalysisStatus
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.schemas.ocr import ExtractedDocument

from .fakes import (
    DEFAULT_VERDICT,
    FakeAIProvider,
    FakeOCRProvider,
    FakeStorageProvider,
)

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"


async def _create_user_and_pending_analysis(*, storage: FakeStorageProvider) -> uuid.UUID:
    async with async_session_factory() as db:
        user = User(email="worker-test@example.com", hashed_password="not-a-real-hash")
        db.add(user)
        await db.flush()

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
        await db.commit()
        return analysis.id


async def _get_analysis(analysis_id: uuid.UUID):
    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        analysis = await repo.get_by_id(analysis_id)
        verdict = await repo.get_verdict(analysis_id)
        return analysis, verdict


@pytest.fixture
def storage() -> FakeStorageProvider:
    return FakeStorageProvider()


async def test_successful_pipeline_produces_a_verdict_and_marks_complete(
    monkeypatch, storage
) -> None:
    analysis_id = await _create_user_and_pending_analysis(storage=storage)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    analysis, verdict = await _get_analysis(analysis_id)
    assert analysis.status == AnalysisStatus.COMPLETE
    assert analysis.error_message is None
    assert verdict is not None
    assert verdict.risk_score == DEFAULT_VERDICT.risk_score
    assert verdict.confidence == DEFAULT_VERDICT.confidence
    assert len(verdict.red_flags) == len(DEFAULT_VERDICT.red_flags)


async def test_ocr_permanent_failure_marks_analysis_failed(monkeypatch, storage) -> None:
    analysis_id = await _create_user_and_pending_analysis(storage=storage)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider(permanent_error=True))
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    analysis, verdict = await _get_analysis(analysis_id)
    assert analysis.status == AnalysisStatus.FAILED
    assert analysis.error_message
    assert verdict is None


async def test_ocr_transient_failure_recovers_on_retry(monkeypatch, storage) -> None:
    analysis_id = await _create_user_and_pending_analysis(storage=storage)

    # Fails once (transient), succeeds on the retry -- proves the retry
    # path actually runs the call again rather than just catching once.
    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(
        worker, "get_ocr_provider", lambda: FakeOCRProvider(transient_error_count=1)
    )
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    analysis, verdict = await _get_analysis(analysis_id)
    assert analysis.status == AnalysisStatus.COMPLETE
    assert verdict is not None


async def test_ai_failure_after_retry_routes_to_manual_review(monkeypatch, storage) -> None:
    analysis_id = await _create_user_and_pending_analysis(storage=storage)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(
        worker, "get_ai_provider", lambda: FakeAIProvider(always_fails=True, transient=True)
    )

    await worker._process_analysis(analysis_id)

    analysis, verdict = await _get_analysis(analysis_id)
    # Never a fabricated low-confidence verdict on provider failure --
    # NEEDS_MANUAL_REVIEW, not FAILED, and definitely no Verdict row.
    assert analysis.status == AnalysisStatus.NEEDS_MANUAL_REVIEW
    assert analysis.error_message
    assert verdict is None


async def test_storage_download_failure_marks_analysis_failed(monkeypatch, storage) -> None:
    analysis_id = await _create_user_and_pending_analysis(storage=storage)
    # Simulate the object having gone missing from the bucket.
    storage.objects.clear()

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    analysis, verdict = await _get_analysis(analysis_id)
    assert analysis.status == AnalysisStatus.FAILED
    assert verdict is None


async def test_unexpected_error_is_not_swallowed(monkeypatch, storage) -> None:
    """A genuinely unexpected bug (not a handled provider error) must
    propagate, not be silently absorbed -- §0.11: no error is silently
    swallowed."""
    analysis_id = await _create_user_and_pending_analysis(storage=storage)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)

    def _boom():
        raise RuntimeError("unexpected bug")

    monkeypatch.setattr(worker, "get_ocr_provider", _boom)

    with pytest.raises(RuntimeError):
        await worker._process_analysis(analysis_id)


async def test_pipeline_merges_rules_engine_matches_into_the_verdict(monkeypatch, storage) -> None:
    """M6: the worker must merge the deterministic rules-engine matches
    with the AI's own red flags, and persist `matched_patterns`,
    `recommended_actions`, and `evidence_coverage` on the resulting
    `Verdict` -- not just the AI's original four fields.
    """
    analysis_id = await _create_user_and_pending_analysis(storage=storage)

    # Trips two of the seeded scam patterns (upfront_processing_fee,
    # urgency_pressure_tactic) -- see migration a1c6f9d2b3e4.
    scam_ocr_text = (
        "Please pay a processing fee within 24 hours to secure this role. "
        "Offer expires today."
    )
    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(
        worker,
        "get_ocr_provider",
        lambda: FakeOCRProvider(document=ExtractedDocument(text=scam_ocr_text, page_count=1)),
    )
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    analysis, verdict = await _get_analysis(analysis_id)
    assert analysis.status == AnalysisStatus.COMPLETE
    assert verdict is not None

    matched_keys = {p["pattern_key"] for p in verdict.matched_patterns}
    assert "upfront_processing_fee" in matched_keys
    assert "urgency_pressure_tactic" in matched_keys

    # Merged: the AI's one LOW-severity flag (from DEFAULT_VERDICT) plus
    # the two pattern-matched flags above.
    assert len(verdict.red_flags) == 1 + len(matched_keys)
    assert verdict.recommended_actions
    assert 0.0 < verdict.evidence_coverage <= 1.0


async def test_pipeline_with_no_pattern_matches_still_persists_empty_m6_fields(
    monkeypatch, storage
) -> None:
    analysis_id = await _create_user_and_pending_analysis(storage=storage)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    _, verdict = await _get_analysis(analysis_id)
    assert verdict is not None
    assert verdict.matched_patterns == []
    assert verdict.recommended_actions  # still populated -- rule-based, not AI-dependent
    assert 0.0 <= verdict.evidence_coverage <= 1.0


async def test_mark_failed_generic_recovers_a_stuck_processing_row(monkeypatch, storage) -> None:
    """This is what the sync `process_analysis` RQ entrypoint calls after
    catching an exception from `_process_analysis`, so a bug never leaves
    a row stuck in PROCESSING forever. Exercised directly here rather than
    through `process_analysis`'s own `asyncio.run()` wrapper, which -- by
    design, matching how RQ actually invokes it in its own worker process
    with no event loop yet running -- cannot be nested inside the event
    loop this async test already runs in.
    """
    analysis_id = await _create_user_and_pending_analysis(storage=storage)

    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        analysis = await repo.get_by_id(analysis_id)
        assert analysis is not None
        await repo.set_status(analysis, AnalysisStatus.PROCESSING)
        await db.commit()

    await worker._mark_failed_generic(analysis_id)

    analysis, verdict = await _get_analysis(analysis_id)
    assert analysis.status == AnalysisStatus.FAILED
    assert verdict is None
