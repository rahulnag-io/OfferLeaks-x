"""Worker integration tests for M7's company resolution/refresh
(`worker._attach_company_profile`, `worker.refresh_company_profile`),
reusing the same fake-provider convention as `test_analysis_worker.py`.
"""

import uuid

from offerleaks import worker
from offerleaks.core.db import async_session_factory
from offerleaks.models.analysis import AnalysisStatus
from offerleaks.models.company import CompanyVerificationStatus
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.company_repository import CompanyRepository
from offerleaks.schemas.ocr import ExtractedDocument

from ..company.fakes import FakeDomainAgeProvider, FakeWebsiteReachabilityProvider
from .fakes import DEFAULT_EXTRACTED_TEXT, FakeAIProvider, FakeOCRProvider, FakeStorageProvider

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

LETTER_WITH_COMPANY = (
    "Offer Letter\n\nOn behalf of: Acme Technologies Inc.\n\n"
    "Dear Alice, we are pleased to offer you the position of Engineer. "
    "Please reach out to hr@acme-technologies.com with any questions.\n\n"
    "Regards,\nAcme Technologies Inc."
)


async def _create_user_and_pending_analysis(
    *, storage: FakeStorageProvider, text: str = DEFAULT_EXTRACTED_TEXT
) -> uuid.UUID:
    async with async_session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
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


async def test_successful_analysis_resolves_and_attaches_a_company(monkeypatch) -> None:
    storage = FakeStorageProvider()
    analysis_id = await _create_user_and_pending_analysis(storage=storage, text=LETTER_WITH_COMPANY)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(
        worker,
        "get_ocr_provider",
        lambda: FakeOCRProvider(document=ExtractedDocument(text=LETTER_WITH_COMPANY, page_count=1)),
    )
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).get_by_id(analysis_id)
        assert analysis.company_id is not None
        company = await CompanyRepository(db).get_by_id(analysis.company_id)
        assert company.domain == "acme-technologies.com"


async def test_analysis_with_no_extractable_company_signals_has_no_company(monkeypatch) -> None:
    storage = FakeStorageProvider()
    analysis_id = await _create_user_and_pending_analysis(storage=storage)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(worker, "get_ocr_provider", lambda: FakeOCRProvider())
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    await worker._process_analysis(analysis_id)

    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).get_by_id(analysis_id)
        assert analysis.company_id is None
        assert analysis.status == AnalysisStatus.COMPLETE  # unaffected by the absence of a company


async def test_company_resolution_failure_never_fails_the_analysis(monkeypatch) -> None:
    """A broken company-resolution step must degrade silently -- the
    analysis pipeline (OCR -> AI -> verdict) is the product; company
    signal is best-effort value-add (M7 §14)."""
    storage = FakeStorageProvider()
    analysis_id = await _create_user_and_pending_analysis(storage=storage, text=LETTER_WITH_COMPANY)

    monkeypatch.setattr(worker, "get_storage_provider", lambda: storage)
    monkeypatch.setattr(
        worker,
        "get_ocr_provider",
        lambda: FakeOCRProvider(document=ExtractedDocument(text=LETTER_WITH_COMPANY, page_count=1)),
    )
    monkeypatch.setattr(worker, "get_ai_provider", lambda: FakeAIProvider())

    async def _broken_attach(db, analysis, text):
        raise RuntimeError("boom")

    monkeypatch.setattr(worker, "_attach_company_profile", _broken_attach)

    await worker._process_analysis(analysis_id)

    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).get_by_id(analysis_id)
        verdict = await AnalysisRepository(db).get_verdict(analysis_id)
        assert analysis.status == AnalysisStatus.COMPLETE
        assert verdict is not None
        assert analysis.company_id is None


async def test_process_company_refresh_writes_a_signal_row():
    async with async_session_factory() as db:
        company = await CompanyRepository(db).get_or_create_by_key(
            normalized_key="domain:refreshme.com", domain="refreshme.com", company_name=None
        )
        await db.commit()
        company_id = company.id


    original_domain_age = worker.get_domain_age_provider
    original_website = worker.get_website_reachability_provider
    worker.get_domain_age_provider = lambda: FakeDomainAgeProvider()
    worker.get_website_reachability_provider = lambda: FakeWebsiteReachabilityProvider()
    try:
        await worker.refresh_company_profile(str(company_id))
    finally:
        worker.get_domain_age_provider = original_domain_age
        worker.get_website_reachability_provider = original_website

    async with async_session_factory() as db:
        signal = await CompanyRepository(db).get_signal(company_id)

    assert signal is not None
    # fake default: NO_RECORD
    assert signal.verification_status == CompanyVerificationStatus.NOT_FOUND


async def test_process_company_refresh_is_a_noop_for_an_unknown_company_id():
    # Must not raise even if the company vanished between enqueue and
    # job execution (e.g. deleted concurrently) -- logged and skipped.
    await worker.refresh_company_profile(str(uuid.uuid4()))


# --- Queue selection CLI (M7 audit fix: dedicated per-queue workers) ---


def test_parse_queue_names_from_argv_defaults_to_none_when_absent():
    assert worker._parse_queue_names_from_argv([]) is None
    assert worker._parse_queue_names_from_argv(["--some-other-flag"]) is None


def test_parse_queue_names_from_argv_parses_a_single_queue():
    assert worker._parse_queue_names_from_argv(["--queues=company_refresh"]) == [
        "company_refresh"
    ]


def test_parse_queue_names_from_argv_parses_multiple_comma_separated_queues():
    assert worker._parse_queue_names_from_argv(["--queues=analysis,company_refresh"]) == [
        "analysis",
        "company_refresh",
    ]


def test_parse_queue_names_from_argv_rejects_an_unknown_queue_name():
    import pytest

    with pytest.raises(ValueError, match="unknown queue name"):
        worker._parse_queue_names_from_argv(["--queues=not_a_real_queue"])


def test_resolve_queues_defaults_to_both_when_none():
    queues = worker._resolve_queues(None)
    assert len(queues) == 2


def test_resolve_queues_selects_only_the_requested_queue():
    queues = worker._resolve_queues(["company_refresh"])
    assert len(queues) == 1
    assert queues[0].name == worker.get_company_queue().name

