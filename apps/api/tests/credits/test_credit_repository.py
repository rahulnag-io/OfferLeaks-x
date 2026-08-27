"""Tests for `CreditRepository` against the real Postgres instance.

These specifically target the invariants that a mocked DB couldn't prove:
real row-level locking under concurrency, and real unique-constraint
enforcement for idempotency.
"""

import asyncio
import uuid

from offerleaks.core.db import async_session_factory
from offerleaks.models.credit import CreditTransactionType
from offerleaks.models.user import User
from offerleaks.repositories.analysis_repository import AnalysisRepository
from offerleaks.repositories.credit_repository import CreditRepository


async def _create_user() -> uuid.UUID:
    async with async_session_factory() as db:
        user = User(email=f"{uuid.uuid4()}@example.com", hashed_password="not-a-real-hash")
        db.add(user)
        await db.flush()
        await db.commit()
        return user.id


async def _create_analysis(user_id: uuid.UUID) -> uuid.UUID:
    """`credit_transactions.analysis_id` has a real FK to `analyses.id` --
    tests exercising that column need an actual row, not just any UUID."""
    async with async_session_factory() as db:
        analysis = await AnalysisRepository(db).create(
            user_id=user_id,
            file_storage_key=f"analyses/{user_id}/{uuid.uuid4()}/offer.pdf",
            file_name="offer.pdf",
            file_mime_type="application/pdf",
            file_size_bytes=100,
            prompt_version="offer_letter_v1",
        )
        await db.commit()
        return analysis.id


async def test_initialize_balance_is_idempotent():
    user_id = await _create_user()

    async with async_session_factory() as db:
        repo = CreditRepository(db)
        balance1, created1 = await repo.initialize_balance(user_id, 3)
        await db.commit()

    async with async_session_factory() as db:
        repo = CreditRepository(db)
        balance2, created2 = await repo.initialize_balance(user_id, 3)
        await db.commit()

    assert created1 is True
    assert created2 is False
    assert balance1.balance == 3
    assert balance2.balance == 3  # not re-granted


async def test_try_consume_succeeds_when_sufficient():
    user_id = await _create_user()
    async with async_session_factory() as db:
        repo = CreditRepository(db)
        await repo.initialize_balance(user_id, 3)
        updated = await repo.try_consume(user_id=user_id, amount=1)
        await db.commit()

    assert updated is not None
    assert updated.balance == 2


async def test_try_consume_fails_when_insufficient():
    user_id = await _create_user()
    async with async_session_factory() as db:
        repo = CreditRepository(db)
        await repo.initialize_balance(user_id, 1)
        await db.commit()

    async with async_session_factory() as db:
        repo = CreditRepository(db)
        updated = await repo.try_consume(user_id=user_id, amount=5)
        await db.commit()

    assert updated is None  # nothing charged

    async with async_session_factory() as db:
        balance = await CreditRepository(db).get_balance(user_id)
    assert balance is not None
    assert balance.balance == 1  # unchanged


async def test_try_consume_never_goes_negative_under_concurrency():
    """User has exactly 1 credit. Two requests race to spend it. Exactly
    one must succeed -- this is the scenario the roadmap calls out
    explicitly (§11)."""
    user_id = await _create_user()
    async with async_session_factory() as db:
        repo = CreditRepository(db)
        await repo.initialize_balance(user_id, 1)
        await db.commit()

    async def _attempt() -> bool:
        async with async_session_factory() as db:
            repo = CreditRepository(db)
            updated = await repo.try_consume(user_id=user_id, amount=1)
            await db.commit()
            return updated is not None

    results = await asyncio.gather(*[_attempt() for _ in range(10)])

    assert results.count(True) == 1
    assert results.count(False) == 9

    async with async_session_factory() as db:
        balance = await CreditRepository(db).get_balance(user_id)
    assert balance is not None
    assert balance.balance == 0  # never negative, exactly one spend landed


async def test_record_transaction_once_is_idempotent_per_analysis_and_type():
    user_id = await _create_user()
    analysis_id = await _create_analysis(user_id)

    async with async_session_factory() as db:
        repo = CreditRepository(db)
        first = await repo.record_transaction_once(
            user_id=user_id, amount=-1, type=CreditTransactionType.CONSUME, analysis_id=None
        )
        await db.commit()
    assert first is not None

    async with async_session_factory() as db:
        repo = CreditRepository(db)
        # Same (analysis_id=None, type) pair as an unrelated grant row is
        # fine (NULLs don't collide) -- but two CONSUME rows for the *same*
        # analysis_id must collide.
        first_scoped = await repo.record_transaction_once(
            user_id=user_id,
            amount=-1,
            type=CreditTransactionType.CONSUME,
            analysis_id=analysis_id,
        )
        await db.commit()
    assert first_scoped is not None

    async with async_session_factory() as db:
        repo = CreditRepository(db)
        duplicate = await repo.record_transaction_once(
            user_id=user_id,
            amount=-1,
            type=CreditTransactionType.CONSUME,
            analysis_id=analysis_id,
        )
        await db.commit()
    assert duplicate is None  # blocked by the unique constraint


async def test_record_transaction_once_conflict_does_not_poison_outer_transaction():
    """A duplicate ledger insert is caught inside a SAVEPOINT -- other
    pending work in the same outer transaction must still be able to
    commit."""
    user_id = await _create_user()
    analysis_id = await _create_analysis(user_id)

    async with async_session_factory() as db:
        repo = CreditRepository(db)
        await repo.initialize_balance(user_id, 5)
        await repo.try_consume(user_id=user_id, amount=1)  # balance 5 -> 4
        await repo.record_transaction_once(
            user_id=user_id, amount=-1, type=CreditTransactionType.CONSUME, analysis_id=analysis_id
        )
        await db.commit()

    async with async_session_factory() as db:
        repo = CreditRepository(db)
        # Duplicate insert for the same (analysis_id, type) -- expect None,
        # but the balance mutation in the same transaction must still land
        # (proving the SAVEPOINT rollback didn't take the outer tx with it).
        await repo.add_balance(user_id=user_id, amount=1)  # balance 4 -> 5
        duplicate = await repo.record_transaction_once(
            user_id=user_id, amount=-1, type=CreditTransactionType.CONSUME, analysis_id=analysis_id
        )
        assert duplicate is None
        await db.commit()

    async with async_session_factory() as db:
        balance = await CreditRepository(db).get_balance(user_id)
    assert balance is not None
    assert balance.balance == 5  # 5 - 1 (consume) + 1 (add_balance) = 5
