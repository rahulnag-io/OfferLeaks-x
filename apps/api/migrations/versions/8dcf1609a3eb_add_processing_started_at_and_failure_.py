"""add processing_started_at and failure_reason to analyses for stuck-analysis recovery

Revision ID: 8dcf1609a3eb
Revises: 527bc9b3203a
Create Date: 2026-08-13 06:28:26.386509

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8dcf1609a3eb'
down_revision: Union[str, Sequence[str], None] = '527bc9b3203a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "analyses",
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        op.f("ix_analyses_processing_started_at"),
        "analyses",
        ["processing_started_at"],
        unique=False,
    )
    op.add_column(
        "analyses",
        sa.Column("failure_reason", sa.String(length=50), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("analyses", "failure_reason")
    op.drop_index(op.f("ix_analyses_processing_started_at"), table_name="analyses")
    op.drop_column("analyses", "processing_started_at")
