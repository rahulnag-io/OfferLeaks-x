"""add plans and plan_entitlements tables

Revision ID: b2d7e0a3c5f6
Revises: a1c6f9d2b3e4
Create Date: 2026-08-16 00:05:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2d7e0a3c5f6'
down_revision: Union[str, Sequence[str], None] = 'a1c6f9d2b3e4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FREE_PLAN_ID = uuid.uuid4()
PRO_PLAN_ID = uuid.uuid4()


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'plans',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('key', sa.String(length=50), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('monthly_credit_grant', sa.Integer(), nullable=False),
        sa.Column('monthly_analysis_limit', sa.Integer(), nullable=True),
        sa.Column('price_amount_minor', sa.Integer(), nullable=False),
        sa.Column('price_currency', sa.String(length=3), nullable=False),
        sa.Column('razorpay_plan_id', sa.String(length=100), nullable=True),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key', name='uq_plans_key'),
    )
    op.create_index(op.f('ix_plans_key'), 'plans', ['key'], unique=False)

    op.create_table(
        'plan_entitlements',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('plan_id', sa.Uuid(), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('value', sa.String(length=500), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('plan_id', 'key', name='uq_plan_entitlements_plan_id_key'),
    )
    op.create_index(op.f('ix_plan_entitlements_plan_id'), 'plan_entitlements', ['plan_id'], unique=False)

    plans_table = sa.table(
        'plans',
        sa.column('id', sa.Uuid()),
        sa.column('key', sa.String()),
        sa.column('name', sa.String()),
        sa.column('monthly_credit_grant', sa.Integer()),
        sa.column('monthly_analysis_limit', sa.Integer()),
        sa.column('price_amount_minor', sa.Integer()),
        sa.column('price_currency', sa.String()),
        sa.column('razorpay_plan_id', sa.String()),
        sa.column('is_active', sa.Boolean()),
    )
    op.bulk_insert(
        plans_table,
        [
            {
                'id': FREE_PLAN_ID,
                'key': 'free',
                'name': 'Free',
                # No recurring grant -- the free plan relies on Version 4's
                # one-time signup bonus (`credit_initial_grant` in config),
                # not a monthly top-up.
                'monthly_credit_grant': 0,
                # Matches M6's DoD ("A Free user is capped at plan
                # limits"). A deliberately conservative starter cap, not
                # derived from any specific business requirement in the
                # roadmap docs -- documented here as the smallest
                # reasonable engineering decision for an otherwise
                # unspecified number.
                'monthly_analysis_limit': 10,
                'price_amount_minor': 0,
                'price_currency': 'INR',
                'razorpay_plan_id': None,
                'is_active': True,
            },
            {
                'id': PRO_PLAN_ID,
                'key': 'pro',
                'name': 'Pro',
                'monthly_credit_grant': 50,
                'monthly_analysis_limit': None,  # unlimited
                # ₹499/month -- a placeholder starter price, in the
                # smallest-currency-unit convention this column uses
                # (499 * 100 paise). Update directly in the `plans` table
                # once real pricing is decided; this migration's job is
                # the schema/plumbing, not the final business price.
                'price_amount_minor': 49900,
                'price_currency': 'INR',
                # Must be filled in manually with the real Razorpay Plan
                # id (`plan_...`) after creating the corresponding plan in
                # the Razorpay dashboard/API -- see the M6 billing
                # integration guide. Subscribing to Pro will fail with a
                # clear error until this is set (see
                # `BillingService.create_subscription`).
                'razorpay_plan_id': None,
                'is_active': True,
            },
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_plan_entitlements_plan_id'), table_name='plan_entitlements')
    op.drop_table('plan_entitlements')
    op.drop_index(op.f('ix_plans_key'), table_name='plans')
    op.drop_table('plans')
