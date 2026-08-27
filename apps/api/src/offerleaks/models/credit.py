"""Credit-system models (Version 4: Credit System).

Two tables, deliberately kept from silently diverging:

- `CreditBalance` is the authoritative *current* balance for a user (one
  row per user, per architecture.md §0.9's `CREDIT_BALANCE` entity). All
  reads that gate an action (\"can this user start an analysis?\") read
  this table.
- `CreditTransaction` is an append-only ledger of every grant/consume/
  refund. It exists for two reasons: (1) audit -- being able to answer
  "why is this user's balance what it is" without guessing, and (2)
  idempotency -- a unique constraint on `(analysis_id, type)` makes "has
  this analysis already been charged/refunded?" a single indexed lookup
  instead of an ad hoc flag, so retries/duplicate jobs/duplicate requests
  can't double-charge or double-refund.

Every balance mutation in `CreditRepository` writes both rows in the same
DB transaction (balance update + ledger insert), so the two can't drift
apart under normal operation. See `services/credit_service.py` for the
transaction-safety contract in detail.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from offerleaks.core.db import Base


class CreditTransactionType(enum.StrEnum):
    GRANT = "grant"
    CONSUME = "consume"
    REFUND = "refund"


class CreditBalance(Base):
    """The authoritative, current credit balance for one user.

    One row per user (enforced by the unique constraint on `user_id`).
    `balance` is an integer -- credits are whole units, never fractional,
    so there's no floating-point drift in accounting.
    """

    __tablename__ = "credit_balances"
    __table_args__ = (
        UniqueConstraint("user_id", name="uq_credit_balances_user_id"),
        CheckConstraint("balance >= 0", name="ck_credit_balances_balance_non_negative"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    balance: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class CreditTransaction(Base):
    """Append-only ledger entry for a single grant/consume/refund.

    `amount` is signed: positive for grant/refund, negative for consume,
    so `sum(amount)` for a user always equals their current balance (a
    useful reconciliation invariant even though the balance itself is
    read from `CreditBalance`, not derived by summing this table on every
    request).

    `analysis_id` is null for account-level grants and non-null for
    analysis-scoped consume/refund entries. The unique constraint on
    `(analysis_id, type)` is the idempotency guard described in the
    module docstring -- Postgres treats each NULL as distinct, so it only
    actually constrains analysis-scoped rows.
    """

    __tablename__ = "credit_transactions"
    __table_args__ = (
        UniqueConstraint(
            "analysis_id", "type", name="uq_credit_transactions_analysis_id_type"
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, server_default=func.gen_random_uuid()
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    analysis_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("analyses.id", ondelete="CASCADE"), nullable=True, index=True
    )

    type: Mapped[CreditTransactionType] = mapped_column(
        Enum(
            CreditTransactionType,
            name="credit_transaction_type",
            values_callable=lambda enum_cls: [member.value for member in enum_cls],
        ),
        nullable=False,
    )
    # Signed: +N for grant/refund, -N for consume.
    amount: Mapped[int] = mapped_column(Integer, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
