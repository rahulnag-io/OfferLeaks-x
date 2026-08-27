"""add subscriptions, webhook_events, and usage_ledger tables

Revision ID: c3e8f1b4d607
Revises: b2d7e0a3c5f6
Create Date: 2026-08-16 00:10:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'c3e8f1b4d607'
down_revision: Union[str, Sequence[str], None] = 'b2d7e0a3c5f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    op.create_table(
        'subscriptions',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('plan_id', sa.Uuid(), nullable=False),
        sa.Column('razorpay_subscription_id', sa.String(length=100), nullable=True),
        sa.Column('razorpay_customer_id', sa.String(length=100), nullable=True),
        sa.Column(
            'status',
            sa.Enum('created', 'active', 'past_due', 'canceled', 'expired', name='subscription_status'),
            nullable=False,
        ),
        sa.Column('current_period_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('cancel_at_period_end', sa.Boolean(), server_default='false', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['plan_id'], ['plans.id'], ondelete='RESTRICT'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('user_id', name='uq_subscriptions_user_id'),
    )
    op.create_index(op.f('ix_subscriptions_user_id'), 'subscriptions', ['user_id'], unique=False)
    op.create_index(op.f('ix_subscriptions_plan_id'), 'subscriptions', ['plan_id'], unique=False)
    op.create_index(
        op.f('ix_subscriptions_razorpay_subscription_id'),
        'subscriptions',
        ['razorpay_subscription_id'],
        unique=True,
    )

    op.create_table(
        'webhook_events',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('provider', sa.String(length=50), nullable=False),
        sa.Column('provider_event_id', sa.String(length=200), nullable=False),
        sa.Column('event_type', sa.String(length=100), nullable=False),
        sa.Column('payload', sa.JSON(), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'provider', 'provider_event_id', name='uq_webhook_events_provider_event_id'
        ),
    )
    op.create_index(
        op.f('ix_webhook_events_provider_event_id'), 'webhook_events', ['provider_event_id'], unique=False
    )
    op.create_index(op.f('ix_webhook_events_event_type'), 'webhook_events', ['event_type'], unique=False)

    op.create_table(
        'usage_ledger',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column('subscription_id', sa.Uuid(), nullable=True),
        sa.Column('period_key', sa.String(length=100), nullable=False),
        sa.Column('credits_granted', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['subscription_id'], ['subscriptions.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint(
            'subscription_id', 'period_key', name='uq_usage_ledger_subscription_period'
        ),
    )
    op.create_index(op.f('ix_usage_ledger_user_id'), 'usage_ledger', ['user_id'], unique=False)
    op.create_index(op.f('ix_usage_ledger_subscription_id'), 'usage_ledger', ['subscription_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_usage_ledger_subscription_id'), table_name='usage_ledger')
    op.drop_index(op.f('ix_usage_ledger_user_id'), table_name='usage_ledger')
    op.drop_table('usage_ledger')

    op.drop_index(op.f('ix_webhook_events_event_type'), table_name='webhook_events')
    op.drop_index(op.f('ix_webhook_events_provider_event_id'), table_name='webhook_events')
    op.drop_table('webhook_events')

    op.drop_index(op.f('ix_subscriptions_razorpay_subscription_id'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_plan_id'), table_name='subscriptions')
    op.drop_index(op.f('ix_subscriptions_user_id'), table_name='subscriptions')
    op.drop_table('subscriptions')
    sa.Enum(name='subscription_status').drop(op.get_bind(), checkfirst=True)
