"""Data access for `UsageLedgerEntry`. See that model's docstring for the
idempotency contract this repository enforces."""

import uuid

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.usage_ledger import UsageLedgerEntry


class UsageLedgerRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record_grant_once(
        self,
        *,
        user_id: uuid.UUID,
        subscription_id: uuid.UUID,
        period_key: str,
        credits_granted: int,
    ) -> UsageLedgerEntry | None:
        """Inserts a grant row for `(subscription_id, period_key)` unless
        one already exists -- in which case returns `None` and the
        caller must not grant credits again for this period. Same
        SAVEPOINT-scoped insert pattern as
        `CreditRepository.record_transaction_once`.
        """
        try:
            async with self._db.begin_nested():
                entry = UsageLedgerEntry(
                    user_id=user_id,
                    subscription_id=subscription_id,
                    period_key=period_key,
                    credits_granted=credits_granted,
                )
                self._db.add(entry)
                await self._db.flush()
            return entry
        except IntegrityError:
            return None
