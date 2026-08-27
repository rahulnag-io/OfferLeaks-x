"""Data access for `CreditBalance`/`CreditTransaction`.

Every mutation here is written to be safe under concurrent callers without
relying on a separate `SELECT ... FOR UPDATE`:

- `try_consume` is a single conditional `UPDATE ... WHERE balance >= amount
  RETURNING ...`. Postgres takes the row lock as part of the `UPDATE`
  itself, so two concurrent requests against the same balance serialize on
  that row -- the second one sees the first's decrement before evaluating
  its own `WHERE balance >= amount`, and gets `None` back if that leaves
  it short. This is what makes "user has 1 credit, two concurrent
  requests, only one succeeds" hold without extra locking.
- `record_transaction_once` inserts a ledger row inside a `SAVEPOINT`
  (`begin_nested`), so a unique-constraint conflict (this analysis was
  already charged/refunded) only rolls back the ledger insert, not
  whatever else is pending in the caller's outer transaction.

Routers and services never issue SQLAlchemy queries directly against
these tables -- they go through this repository (architecture.md §0.3).
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.credit import CreditBalance, CreditTransaction, CreditTransactionType


class CreditRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def get_balance(self, user_id: uuid.UUID) -> CreditBalance | None:
        result = await self._db.execute(
            select(CreditBalance).where(CreditBalance.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def initialize_balance(
        self, user_id: uuid.UUID, initial_balance: int
    ) -> tuple[CreditBalance, bool]:
        """Idempotently ensures a balance row exists for `user_id`.

        Returns `(balance, created)`. Safe to call more than once for the
        same user (e.g. a replayed registration request, or a race between
        two requests creating the same user) -- the unique constraint on
        `user_id` plus `ON CONFLICT DO NOTHING` guarantees at most one row
        is ever created, and `created` tells the caller whether *this*
        call was the one that created it (so it can record a single GRANT
        ledger entry rather than one per call).
        """
        stmt = (
            pg_insert(CreditBalance)
            .values(user_id=user_id, balance=initial_balance)
            .on_conflict_do_nothing(index_elements=["user_id"])
            .returning(CreditBalance)
        )
        result = await self._db.execute(stmt)
        row = result.scalar_one_or_none()
        await self._db.flush()
        if row is not None:
            return row, True

        existing = await self.get_balance(user_id)
        if existing is None:
            # Should be unreachable: ON CONFLICT DO NOTHING only no-ops if a
            # row already exists. Guard anyway rather than returning None.
            raise RuntimeError(f"credit balance missing for user {user_id} after init")
        return existing, False

    async def try_consume(self, *, user_id: uuid.UUID, amount: int) -> CreditBalance | None:
        """Atomically decrements the balance by `amount` iff sufficient.

        Returns the updated row, or `None` if the balance was insufficient
        (nothing is changed in that case). `amount` must be positive.
        """
        if amount <= 0:
            raise ValueError("amount must be positive")

        stmt = (
            update(CreditBalance)
            .where(CreditBalance.user_id == user_id, CreditBalance.balance >= amount)
            .values(balance=CreditBalance.balance - amount)
            .returning(CreditBalance)
        )
        result = await self._db.execute(stmt)
        row = result.scalar_one_or_none()
        await self._db.flush()
        return row

    async def add_balance(self, *, user_id: uuid.UUID, amount: int) -> CreditBalance:
        """Atomically increments the balance by `amount` (grants, refunds).

        `amount` must be positive; there is no "negative grant" -- consumption
        goes through `try_consume` so it can enforce the non-negative floor.
        """
        if amount <= 0:
            raise ValueError("amount must be positive")

        stmt = (
            update(CreditBalance)
            .where(CreditBalance.user_id == user_id)
            .values(balance=CreditBalance.balance + amount)
            .returning(CreditBalance)
        )
        result = await self._db.execute(stmt)
        row = result.scalar_one_or_none()
        await self._db.flush()
        if row is None:
            raise RuntimeError(f"no credit balance row for user {user_id}")
        return row

    async def record_transaction_once(
        self,
        *,
        user_id: uuid.UUID,
        amount: int,
        type: CreditTransactionType,  # noqa: A002 - matches the model field name
        analysis_id: uuid.UUID | None,
    ) -> CreditTransaction | None:
        """Inserts a ledger row, unless one already exists for
        `(analysis_id, type)` -- in which case it returns `None` and makes
        no change. Runs in a SAVEPOINT so a conflict here doesn't poison
        the caller's outer transaction.
        """
        try:
            async with self._db.begin_nested():
                txn = CreditTransaction(
                    user_id=user_id, analysis_id=analysis_id, type=type, amount=amount
                )
                self._db.add(txn)
                await self._db.flush()
            return txn
        except IntegrityError:
            return None

    async def has_transaction(
        self, *, analysis_id: uuid.UUID, type: CreditTransactionType  # noqa: A002
    ) -> bool:
        result = await self._db.execute(
            select(CreditTransaction.id).where(
                CreditTransaction.analysis_id == analysis_id, CreditTransaction.type == type
            )
        )
        return result.scalar_one_or_none() is not None

    async def get_consume_amounts_for(
        self, analysis_ids: list[uuid.UUID]
    ) -> dict[uuid.UUID, int]:
        """Bulk lookup of what each analysis in `analysis_ids` was actually
        charged (the CONSUME ledger row's amount, stored negative -- see
        the module docstring -- returned here as a positive cost for
        display). An id with no CONSUME row (e.g. a free re-check, see
        `AnalysisService.recheck_analysis`) is simply absent from the
        result rather than mapped to 0, so callers can distinguish "never
        charged" from "charged 0" if that ever matters.

        Version 5 dashboard/history read path only -- never used to gate
        or mutate anything, so it doesn't need the same concurrency
        guarantees as `try_consume`/`record_transaction_once`.
        """
        if not analysis_ids:
            return {}
        result = await self._db.execute(
            select(CreditTransaction.analysis_id, CreditTransaction.amount).where(
                CreditTransaction.analysis_id.in_(analysis_ids),
                CreditTransaction.type == CreditTransactionType.CONSUME,
            )
        )
        return {row.analysis_id: -row.amount for row in result if row.analysis_id is not None}

    async def get_refunded_analysis_ids(self, analysis_ids: list[uuid.UUID]) -> set[uuid.UUID]:
        """Bulk lookup of which of `analysis_ids` have a REFUND ledger row
        -- i.e. were charged but later given back (worker-side failure,
        or the stuck-analysis reconciliation sweep in
        `offerleaks/reconciliation.py`). Read path only, same rationale as
        `get_consume_amounts_for`: the ledger (via `refund_for_analysis`'s
        unique-constrained insert) is the actual source of truth for "was
        this refunded," this is just a display-time lookup over it, not a
        second copy of that fact.
        """
        if not analysis_ids:
            return set()
        result = await self._db.execute(
            select(CreditTransaction.analysis_id).where(
                CreditTransaction.analysis_id.in_(analysis_ids),
                CreditTransaction.type == CreditTransactionType.REFUND,
            )
        )
        return {row for row in result.scalars().all() if row is not None}
