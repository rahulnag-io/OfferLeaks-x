"""Credit business logic (Version 4: Credit System).

This is the *only* place in the codebase allowed to decide whether an
analysis may proceed on credit grounds, or to mutate a balance. Routers,
`AnalysisService`, and the worker all ask this service rather than doing
their own arithmetic (architecture.md §0.2: "the backend must be the
authoritative source of truth for credit balances and credit consumption").

Transaction-safety contract (read this before changing this file):

- `charge_for_analysis` and `refund_for_analysis` do **not** call
  `db.commit()` themselves. They're designed to run inside whatever
  transaction the caller is already managing, so a credit mutation and
  the analysis-record change it's paired with commit or roll back
  together. Callers must commit.
- Both are idempotent per `analysis_id`: calling either twice for the
  same analysis is a safe no-op the second time (backed by the unique
  ledger constraint in `CreditRepository`), which is what makes worker
  retries and duplicate requests safe.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.core.config import Settings, get_settings
from offerleaks.models.credit import CreditTransactionType
from offerleaks.repositories.credit_repository import CreditRepository


class CreditServiceError(Exception):
    """Base class for all credit-service failures."""


class InsufficientCreditsError(CreditServiceError):
    def __init__(self, *, required: int, available: int) -> None:
        super().__init__(f"required {required} credits, {available} available")
        self.required = required
        self.available = available


@dataclass(frozen=True, slots=True)
class CreditChargeResult:
    analysis_id: uuid.UUID
    amount_charged: int
    remaining_balance: int


class CreditService:
    def __init__(self, db: AsyncSession, settings: Settings | None = None) -> None:
        self._db = db
        self._credits = CreditRepository(db)
        self._settings = settings or get_settings()

    @property
    def cost_per_analysis(self) -> int:
        """The server-side, non-negotiable cost of one analysis. Never
        accept this value from a client -- see architecture.md §0.10."""
        return self._settings.credit_cost_per_analysis

    async def get_balance(self, user_id: uuid.UUID) -> int:
        balance = await self._credits.get_balance(user_id)
        return balance.balance if balance is not None else 0

    async def grant_initial_credits(self, user_id: uuid.UUID) -> int:
        """Grants the configured signup bonus, exactly once per user.

        Must be called in the same DB transaction as the user's creation
        (i.e. before the caller's `db.commit()`) so a crash between "user
        row created" and "balance row created" can't happen -- and safe to
        call again for the same user regardless (idempotent via the unique
        constraint on `credit_balances.user_id`).
        """
        balance, created = await self._credits.initialize_balance(
            user_id, self._settings.credit_initial_grant
        )
        if created:
            await self._credits.record_transaction_once(
                user_id=user_id,
                amount=self._settings.credit_initial_grant,
                type=CreditTransactionType.GRANT,
                analysis_id=None,
            )
        return balance.balance

    async def grant_subscription_credits(self, *, user_id: uuid.UUID, amount: int) -> int:
        """Grants `amount` credits from a subscription renewal (M6).

        Unlike `grant_initial_credits`, this method carries **no
        idempotency guard of its own** -- calling it twice adds credits
        twice. That's intentional: a recurring grant has no natural
        per-call idempotency key the way a one-time signup grant does
        (`user_id` alone). The caller (`BillingService`) is responsible
        for calling this at most once per billing period, enforced via
        `UsageLedgerRepository.record_grant_once`'s unique constraint
        *before* calling this -- see that module. Requires the user's
        `credit_balances` row to already exist (true for every user post
        Version 4 registration).
        """
        balance = await self._credits.add_balance(user_id=user_id, amount=amount)
        await self._credits.record_transaction_once(
            user_id=user_id,
            amount=amount,
            type=CreditTransactionType.GRANT,
            analysis_id=None,
        )
        return balance.balance

    async def charge_for_analysis(
        self, *, user_id: uuid.UUID, analysis_id: uuid.UUID
    ) -> CreditChargeResult:
        """Atomically charges `cost_per_analysis` credits to `user_id` for
        `analysis_id`.

        Raises `InsufficientCreditsError` (and changes nothing) if the
        balance is too low. Idempotent: a second call for the same
        `analysis_id` that somehow still had a sufficient balance would
        detect the existing CONSUME ledger row, refund the balance it just
        took, and raise -- so an accidental double-call can't double-charge.
        """
        cost = self.cost_per_analysis

        updated = await self._credits.try_consume(user_id=user_id, amount=cost)
        if updated is None:
            current = await self.get_balance(user_id)
            raise InsufficientCreditsError(required=cost, available=current)

        txn = await self._credits.record_transaction_once(
            user_id=user_id,
            amount=-cost,
            type=CreditTransactionType.CONSUME,
            analysis_id=analysis_id,
        )
        if txn is None:
            # Defense in depth: this analysis was already charged (e.g. a
            # re-entrant call). Give back what we just conditionally took
            # so the balance isn't double-decremented, and surface it as an
            # error rather than silently succeeding twice.
            await self._credits.add_balance(user_id=user_id, amount=cost)
            raise CreditServiceError(
                f"analysis {analysis_id} was already charged; charge not applied twice"
            )

        return CreditChargeResult(
            analysis_id=analysis_id, amount_charged=cost, remaining_balance=updated.balance
        )

    async def refund_for_analysis(
        self, *, user_id: uuid.UUID, analysis_id: uuid.UUID, amount: int | None = None
    ) -> bool:
        """Restores credits for an analysis that was charged but could not
        be completed (see `worker.py` for exactly which failure paths
        trigger this).

        Returns `True` if a refund was applied, `False` if this analysis
        was already refunded (idempotent no-op -- safe to call from a
        retried worker job). Refunding an analysis that was never charged
        (no CONSUME ledger row) is also a safe no-op: it's guarded the same
        way, since there's nothing meaningful to reconcile against.
        """
        cost = amount if amount is not None else self.cost_per_analysis

        was_charged = await self._credits.has_transaction(
            analysis_id=analysis_id, type=CreditTransactionType.CONSUME
        )
        if not was_charged:
            return False

        txn = await self._credits.record_transaction_once(
            user_id=user_id,
            amount=cost,
            type=CreditTransactionType.REFUND,
            analysis_id=analysis_id,
        )
        if txn is None:
            # Already refunded.
            return False

        await self._credits.add_balance(user_id=user_id, amount=cost)
        return True
