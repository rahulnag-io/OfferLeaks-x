"""add credit system tables

Revision ID: 9a1c2d7e4f10
Revises: 568093daa50f
Create Date: 2026-08-11 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a1c2d7e4f10'
down_revision: Union[str, Sequence[str], None] = '568093daa50f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'credit_balances',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('balance', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.CheckConstraint('balance >= 0', name='ck_credit_balances_balance_non_negative'),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_credit_balances_user_id'),
    )
    op.create_index(op.f('ix_credit_balances_user_id'), 'credit_balances', ['user_id'], unique=False)

    op.create_table(
        'credit_transactions',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('analysis_id', sa.Uuid(), nullable=True),
        sa.Column('type', sa.Enum('grant', 'consume', 'refund', name='credit_transaction_type'), nullable=False),
        sa.Column('amount', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        # The idempotency guard: at most one CONSUME and at most one REFUND
        # ledger row per analysis. NULLs (grant rows, which have no
        # analysis_id) are not constrained against each other by Postgres.
        sa.UniqueConstraint('analysis_id', 'type', name='uq_credit_transactions_analysis_id_type'),
    )
    op.create_index(op.f('ix_credit_transactions_user_id'), 'credit_transactions', ['user_id'], unique=False)
    op.create_index(op.f('ix_credit_transactions_analysis_id'), 'credit_transactions', ['analysis_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_credit_transactions_analysis_id'), table_name='credit_transactions')
    op.drop_index(op.f('ix_credit_transactions_user_id'), table_name='credit_transactions')
    op.drop_table('credit_transactions')
    op.drop_index(op.f('ix_credit_balances_user_id'), table_name='credit_balances')
    op.drop_table('credit_balances')
    # Same known Alembic/Postgres ENUM-on-table-drop limitation handled in
    # earlier migrations -- without this, re-running upgrade after a
    # downgrade fails with "type already exists".
    sa.Enum(name='credit_transaction_type').drop(op.get_bind(), checkfirst=True)
