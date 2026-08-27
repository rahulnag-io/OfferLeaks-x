"""Data access for `WebhookEvent`. See that model's docstring for the
idempotency contract this repository enforces."""

from datetime import datetime
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from offerleaks.models.webhook_event import WebhookEvent


class WebhookRepository:
    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def record_once(
        self,
        *,
        provider: str,
        provider_event_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> WebhookEvent | None:
        """Inserts a `WebhookEvent` row, unless `(provider,
        provider_event_id)` already exists -- in which case returns
        `None` and makes no change (this is a replayed/redelivered
        webhook; the caller must treat it as already handled and return
        2xx without redoing any side effect). SAVEPOINT-scoped, same
        pattern as `CreditRepository.record_transaction_once`.
        """
        try:
            async with self._db.begin_nested():
                event = WebhookEvent(
                    provider=provider,
                    provider_event_id=provider_event_id,
                    event_type=event_type,
                    payload=payload,
                )
                self._db.add(event)
                await self._db.flush()
            return event
        except IntegrityError:
            return None

    async def mark_processed(self, event: WebhookEvent, *, processed_at: datetime) -> None:
        event.processed_at = processed_at
        await self._db.flush()
