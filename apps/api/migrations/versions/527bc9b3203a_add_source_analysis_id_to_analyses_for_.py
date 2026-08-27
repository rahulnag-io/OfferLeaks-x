"""add source_analysis_id and free_recheck_claimed to analyses

Revision ID: 527bc9b3203a
Revises: 9a1c2d7e4f10
Create Date: 2026-08-13 01:07:36.339338

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '527bc9b3203a'
down_revision: Union[str, Sequence[str], None] = '9a1c2d7e4f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.add_column(
        "analyses",
        sa.Column("source_analysis_id", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "fk_analyses_source_analysis_id_analyses",
        "analyses",
        "analyses",
        ["source_analysis_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        op.f("ix_analyses_source_analysis_id"),
        "analyses",
        ["source_analysis_id"],
        unique=False,
    )

    # Claimed atomically by `AnalysisRepository.try_claim_free_recheck`
    # (a single conditional `UPDATE ... WHERE free_recheck_claimed = false
    # RETURNING ...`, the same pattern `CreditRepository.try_consume` uses)
    # so two concurrent re-check requests for the same source analysis
    # can't both land the one free re-check the pricing rule allows.
    op.add_column(
        "analyses",
        sa.Column(
            "free_recheck_claimed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column("analyses", "free_recheck_claimed")
    op.drop_index(op.f("ix_analyses_source_analysis_id"), table_name="analyses")
    op.drop_constraint(
        "fk_analyses_source_analysis_id_analyses", "analyses", type_="foreignkey"
    )
    op.drop_column("analyses", "source_analysis_id")
