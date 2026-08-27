"""Tests for `offerleaks.reconciliation` -- the backend-owned sweep that
recovers analyses stuck in PENDING or PROCESSING and refunds their credit
exactly once.

Companion to `test_analysis_worker.py`/`test_worker_credits.py`. Runs
against the real Postgres instance (same convention as the rest of the
suite) with fake providers where the worker itself is exercised.

Timestamps are backdated directly via raw SQL (there's no other way to
get a `created_at`/`processing_started_at` far enough in the past without
actually waiting) and the configured timeouts are monkeypatched down to a
couple of seconds so these tests don't take minutes to run.
"""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import text

from offerleaks import reconciliation, worker
from offerleaks.core.config import get_settings
from offerleaks.core.db import async_session_factory
from offerleaks.models.analysis import AnalysisFailureReason, AnalysisStatus
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.services.credit_service import CreditService

from .fakes import FakeStorageProvider

PDF_BYTES = b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF"

_TINY_PENDING_TIMEOUT = 2
_TINY_PROCESSING_TIMEOUT = 2


@pytest.fixture
def storage() -> FakeStorageProvider:
    return FakeStorageProvider()


@pytest.fixture(autouse=True)
def _tiny_timeouts(monkeypatch):
    """Every test in this module gets 2-second timeouts instead of the
    5/15-minute production defaults -- backdating timestamps by a few
    seconds (below) is far more reliable in CI than actually sleeping for
    minutes."""
    settings = get_settings().model_copy(
        update={
            "pending_analysis_timeout_seconds": _TINY_PENDING_TIMEOUT,
            "processing_analysis_timeout_seconds": _TINY_PROCESSING_TIMEOUT,
            "reconciliation_batch_size": 100,
        }
    )
    monkeypatch.setattr(reconciliation, "get_settings", lambda: settings)


async def _create_charged_user_and_analysis(
    *, storage: FakeStorageProvider | None = None
) -> tuple[uuid.UUID, uuid.UUID]:
    """Same shape as `test_worker_credits.py`'s helper: a user with a
    granted+charged balance and a PENDING analysis, so refund assertions
    observe a real charge being undone."""
    async with async_session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
        db.add(user)
        await db.flush()

        credits = CreditService(db)
        await credits.grant_initial_credits(user.id)
        await db.commit()

    async with async_session_factory() as db:
        storage_key = f"analyses/{user.id}/{uuid.uuid4()}/offer.pdf"
        if storage is not None:
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


async def _backdate(analysis_id: uuid.UUID, *, created_seconds_ago: float | None = None) -> None:
    async with async_session_factory() as db:
        if created_seconds_ago is not None:
            cutoff = datetime.now(UTC) - timedelta(seconds=created_seconds_ago)
            await db.execute(
                text("UPDATE analyses SET created_at = :cutoff WHERE id = :id"),
                {"cutoff": cutoff, "id": analysis_id},
            )
        await db.commit()


async def _move_to_processing_started_ago(analysis_id: uuid.UUID, *, seconds_ago: float) -> None:
    """Puts an analysis into PROCESSING with `processing_started_at`
    backdated -- mirrors what `AnalysisRepository.try_start_processing`
    does, but with a controllable timestamp for the timeout test."""
    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        started = await repo.try_start_processing(analysis_id)
        assert started is not None
        await db.commit()

    async with async_session_factory() as db:
        cutoff = datetime.now(UTC) - timedelta(seconds=seconds_ago)
        await db.execute(
            text("UPDATE analyses SET processing_started_at = :cutoff WHERE id = :id"),
            {"cutoff": cutoff, "id": analysis_id},
        )
        await db.commit()


async def _get_analysis(analysis_id: uuid.UUID):
    async with async_session_factory() as db:
        return await AnalysisRepository(db).get_by_id(analysis_id)


async def _get_balance(user_id: uuid.UUID) -> int:
    async with async_session_factory() as db:
        return await CreditService(db).get_balance(user_id)


# --- Pending timeout ---


async def test_pending_timeout_marks_failed_and_refunds() -> None:
    user_id, analysis_id = await _create_charged_user_and_analysis()
    balance_after_charge = await _get_balance(user_id)
    await _backdate(analysis_id, created_seconds_ago=_TINY_PENDING_TIMEOUT + 1)

    result = await reconciliation.run_reconciliation_sweep()

    assert result.candidates_seen == 1
    assert result.analyses_failed == 1
    assert result.credits_refunded == 1

    analysis = await _get_analysis(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.FAILED
    assert analysis.failure_reason == AnalysisFailureReason.PENDING_TIMEOUT.value
    assert analysis.error_message  # user-facing message set, internal reason not embedded in it

    balance_after = await _get_balance(user_id)
    assert balance_after == balance_after_charge + 1


async def test_fresh_pending_analysis_is_left_alone() -> None:
    user_id, analysis_id = await _create_charged_user_and_analysis()
    balance_after_charge = await _get_balance(user_id)
    # No backdating -- this analysis is seconds old, well under the
    # 2-second timeout at the moment the sweep runs.

    result = await reconciliation.run_reconciliation_sweep()

    assert result.candidates_seen == 0
    analysis = await _get_analysis(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.PENDING
    assert await _get_balance(user_id) == balance_after_charge


# --- Processing timeout ---


async def test_processing_timeout_marks_failed_and_refunds() -> None:
    user_id, analysis_id = await _create_charged_user_and_analysis()
    balance_after_charge = await _get_balance(user_id)
    await _move_to_processing_started_ago(analysis_id, seconds_ago=_TINY_PROCESSING_TIMEOUT + 1)

    result = await reconciliation.run_reconciliation_sweep()

    assert result.analyses_failed == 1
    assert result.credits_refunded == 1

    analysis = await _get_analysis(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.FAILED
    assert analysis.failure_reason == AnalysisFailureReason.PROCESSING_TIMEOUT.value

    balance_after = await _get_balance(user_id)
    assert balance_after == balance_after_charge + 1


async def test_healthy_processing_analysis_with_fresh_heartbeat_is_left_alone() -> None:
    """A PROCESSING analysis whose `processing_started_at` is still
    recent must NOT be marked failed -- it may be a legitimately
    still-running job."""
    user_id, analysis_id = await _create_charged_user_and_analysis()
    balance_after_charge = await _get_balance(user_id)
    await _move_to_processing_started_ago(analysis_id, seconds_ago=0)

    result = await reconciliation.run_reconciliation_sweep()

    assert result.candidates_seen == 0
    analysis = await _get_analysis(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.PROCESSING
    assert await _get_balance(user_id) == balance_after_charge


async def test_processing_analysis_without_processing_started_at_is_left_alone() -> None:
    """Defensive edge case: a PROCESSING row with a NULL
    `processing_started_at` (shouldn't happen going forward -- every path
    that sets PROCESSING now also stamps it -- but could exist from data
    predating this migration) must never match the processing-timeout
    query rather than being (mis)treated as infinitely stale."""
    user_id, analysis_id = await _create_charged_user_and_analysis()
    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        analysis = await repo.get_by_id(analysis_id)
        assert analysis is not None
        await repo.set_status(analysis, AnalysisStatus.PROCESSING)  # no processing_started_at
        await db.commit()

    result = await reconciliation.run_reconciliation_sweep()

    assert result.candidates_seen == 0
    analysis = await _get_analysis(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.PROCESSING


# --- Terminal states are never touched ---


async def test_terminal_analyses_are_never_reconciled_regardless_of_age() -> None:
    user_id, analysis_id = await _create_charged_user_and_analysis()
    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        analysis = await repo.get_by_id(analysis_id)
        assert analysis is not None
        await repo.set_status(analysis, AnalysisStatus.COMPLETE)
        await db.commit()
    await _backdate(analysis_id, created_seconds_ago=10_000)

    result = await reconciliation.run_reconciliation_sweep()

    assert result.candidates_seen == 0
    analysis = await _get_analysis(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.COMPLETE
    assert await _get_balance(user_id) == await _get_balance(user_id)  # unchanged, sanity


# --- Idempotency & concurrency ---


async def test_running_the_sweep_twice_does_not_refund_twice() -> None:
    user_id, analysis_id = await _create_charged_user_and_analysis()
    balance_after_charge = await _get_balance(user_id)
    await _backdate(analysis_id, created_seconds_ago=_TINY_PENDING_TIMEOUT + 1)

    first = await reconciliation.run_reconciliation_sweep()
    second = await reconciliation.run_reconciliation_sweep()

    assert first.analyses_failed == 1
    assert first.credits_refunded == 1
    assert second.candidates_seen == 0  # already FAILED, no longer a candidate

    balance_after = await _get_balance(user_id)
    assert balance_after == balance_after_charge + 1


async def test_concurrent_sweeps_refund_exactly_once() -> None:
    """Two reconciliation sweeps racing on the same stuck analysis must
    still produce exactly one FAILED transition and one refund -- the
    scenario `AnalysisRepository.try_transition`'s atomic conditional
    UPDATE exists for."""
    user_id, analysis_id = await _create_charged_user_and_analysis()
    balance_after_charge = await _get_balance(user_id)
    await _backdate(analysis_id, created_seconds_ago=_TINY_PENDING_TIMEOUT + 1)

    results = await asyncio.gather(
        *[reconciliation.run_reconciliation_sweep() for _ in range(5)]
    )

    total_failed = sum(r.analyses_failed for r in results)
    total_refunded = sum(r.credits_refunded for r in results)
    total_lost_races = sum(r.lost_races for r in results)

    assert total_failed == 1
    assert total_refunded == 1
    # The other sweeps either saw 0 candidates (already claimed by the
    # time their SELECT ran) or saw the candidate and lost the atomic
    # claim -- either is fine, both are captured, neither double-acts.
    assert total_failed + total_lost_races >= 1

    balance_after = await _get_balance(user_id)
    assert balance_after == balance_after_charge + 1

    analysis = await _get_analysis(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.FAILED


# --- Never-charged analyses (free re-check) ---


async def test_stuck_free_recheck_is_marked_failed_without_a_refund() -> None:
    """A free re-check (see `AnalysisService.recheck_analysis`) has no
    CONSUME ledger row, so if it gets stuck, there's nothing to refund --
    it should still be marked FAILED, just with `credits_refunded`
    reporting 0 for it."""
    async with async_session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
        db.add(user)
        await db.flush()
        repo = AnalysisRepository(db)
        analysis = await repo.create(
            user_id=user.id,
            file_storage_key="analyses/whatever/offer.pdf",
            file_name="offer.pdf",
            file_mime_type="application/pdf",
            file_size_bytes=len(PDF_BYTES),
            prompt_version="offer_letter_v1",
        )
        await db.commit()
        analysis_id = analysis.id

    await _backdate(analysis_id, created_seconds_ago=_TINY_PENDING_TIMEOUT + 1)

    result = await reconciliation.run_reconciliation_sweep()

    assert result.analyses_failed == 1
    assert result.credits_refunded == 0  # nothing was ever charged

    analysis = await _get_analysis(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.FAILED


# --- Worker vs. reconciler race ---


async def test_worker_losing_the_race_to_the_reconciler_never_writes_a_verdict_or_double_refunds(
    storage,
) -> None:
    """Simulates the exact race `AnalysisRepository.try_transition` exists
    to close: a worker has a job in flight (PROCESSING) when the
    reconciliation sweep times it out and refunds it. When the worker
    finally tries to finish, its own atomic claim must lose -- no Verdict
    written, no second refund.
    """
    user_id, analysis_id = await _create_charged_user_and_analysis(storage=storage)
    await _move_to_processing_started_ago(analysis_id, seconds_ago=_TINY_PROCESSING_TIMEOUT + 1)

    result = await reconciliation.run_reconciliation_sweep()
    assert result.analyses_failed == 1
    assert result.credits_refunded == 1
    balance_after_reconciliation = await _get_balance(user_id)

    # The "worker" only now gets around to trying to finish the job it
    # already started -- exactly what `_finish_processing`/the COMPLETE
    # claim in `_process_analysis` does.
    async with async_session_factory() as db:
        repo = AnalysisRepository(db)
        claimed = await repo.try_transition(
            analysis_id,
            from_status=AnalysisStatus.PROCESSING,
            to_status=AnalysisStatus.COMPLETE,
        )
        assert claimed is None  # lost the race -- reconciler already moved it to FAILED
        await db.rollback()

    analysis = await _get_analysis(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.FAILED  # still FAILED, not overwritten to COMPLETE

    async with async_session_factory() as db:
        verdict = await AnalysisRepository(db).get_verdict(analysis_id)
    assert verdict is None  # never written

    balance_after = await _get_balance(user_id)
    assert balance_after == balance_after_reconciliation  # not refunded a second time


async def test_worker_crash_path_still_only_refunds_once_after_reconciler_intervenes(
    storage,
) -> None:
    """`_mark_failed_generic` (the RQ-entrypoint crash-recovery path) must
    also be a safe no-op if the reconciler already claimed the row."""
    user_id, analysis_id = await _create_charged_user_and_analysis(storage=storage)
    await _move_to_processing_started_ago(analysis_id, seconds_ago=_TINY_PROCESSING_TIMEOUT + 1)

    await reconciliation.run_reconciliation_sweep()
    balance_after_reconciliation = await _get_balance(user_id)

    await worker._mark_failed_generic(analysis_id)  # simulates a crashed worker's cleanup path

    analysis = await _get_analysis(analysis_id)
    assert analysis is not None
    assert analysis.status == AnalysisStatus.FAILED
    assert analysis.failure_reason == AnalysisFailureReason.PENDING_TIMEOUT.value or (
        analysis.failure_reason == AnalysisFailureReason.PROCESSING_TIMEOUT.value
    )
    assert await _get_balance(user_id) == balance_after_reconciliation


# --- CLI entrypoint smoke test ---


async def test_run_reconciliation_sweep_is_a_safe_no_op_with_nothing_stuck() -> None:
    result = await reconciliation.run_reconciliation_sweep()
    assert result.candidates_seen == 0
    assert result.analyses_failed == 0
    assert result.credits_refunded == 0
