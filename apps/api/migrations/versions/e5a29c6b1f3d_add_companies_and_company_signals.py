"""add companies and company_signals tables, analyses.company_id

Revision ID: e5a29c6b1f3d
Revises: c3e8f1b4d607
Create Date: 2026-08-22 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'e5a29c6b1f3d'
down_revision: Union[str, Sequence[str], None] = 'c3e8f1b4d607'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- companies ---
    op.create_table(
        'companies',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('normalized_key', sa.String(length=320), nullable=False),
        sa.Column('domain', sa.String(length=255), nullable=True),
        sa.Column('company_name', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(
        op.f('ix_companies_normalized_key'), 'companies', ['normalized_key'], unique=True
    )
    op.create_index(op.f('ix_companies_domain'), 'companies', ['domain'], unique=False)

    # --- company_signals ---
    op.create_table(
        'company_signals',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('company_id', sa.Uuid(), nullable=False),
        sa.Column(
            'verification_status',
            sa.Enum(
                'found', 'not_found', 'insufficient_evidence',
                name='company_verification_status',
            ),
            server_default='insufficient_evidence',
            nullable=False,
        ),
        sa.Column('domain_age_days', sa.Integer(), nullable=True),
        sa.Column('domain_registered_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            'domain_age_check',
            sa.Enum(
                'ok', 'not_configured', 'unavailable', 'timeout', 'rate_limited',
                'malformed_response', 'no_record',
                name='provider_check_outcome',
            ),
            server_default='not_configured',
            nullable=False,
        ),
        sa.Column('website_reachable', sa.Boolean(), nullable=True),
        sa.Column(
            'website_reachability_check',
            sa.Enum(
                'ok', 'not_configured', 'unavailable', 'timeout', 'rate_limited',
                'malformed_response', 'no_record',
                name='provider_check_outcome',
            ),
            server_default='not_configured',
            nullable=False,
        ),
        sa.Column('email_domain_match', sa.Boolean(), nullable=True),
        sa.Column('last_checked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('evidence_ratio', sa.Float(), server_default='0.0', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('company_id', name='uq_company_signals_company_id'),
    )
    op.create_index(
        op.f('ix_company_signals_company_id'), 'company_signals', ['company_id'], unique=True
    )

    # --- analyses.company_id ---
    op.add_column('analyses', sa.Column('company_id', sa.Uuid(), nullable=True))
    op.create_index(op.f('ix_analyses_company_id'), 'analyses', ['company_id'], unique=False)
    op.create_foreign_key(
        'fk_analyses_company_id_companies',
        'analyses', 'companies',
        ['company_id'], ['id'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_constraint('fk_analyses_company_id_companies', 'analyses', type_='foreignkey')
    op.drop_index(op.f('ix_analyses_company_id'), table_name='analyses')
    op.drop_column('analyses', 'company_id')

    op.drop_index(op.f('ix_company_signals_company_id'), table_name='company_signals')
    op.drop_table('company_signals')

    op.drop_index(op.f('ix_companies_domain'), table_name='companies')
    op.drop_index(op.f('ix_companies_normalized_key'), table_name='companies')
    op.drop_table('companies')

    sa.Enum(name='provider_check_outcome').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='company_verification_status').drop(op.get_bind(), checkfirst=True)
