"""add reports table and company_signal reputation columns

Revision ID: f41af4ad6938
Revises: e5a29c6b1f3d
Create Date: 2026-08-25 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'f41af4ad6938'
down_revision: Union[str, Sequence[str], None] = 'e5a29c6b1f3d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # --- reports ---
    op.create_table(
        'reports',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('user_id', sa.Uuid(), nullable=False),
        sa.Column(
            'target_type',
            sa.Enum('company', 'offer', 'recruiter', 'website', name='report_target_type'),
            nullable=False,
        ),
        sa.Column('company_id', sa.Uuid(), nullable=True),
        sa.Column('analysis_id', sa.Uuid(), nullable=True),
        sa.Column('target_detail', sa.String(length=500), nullable=True),
        sa.Column('reasons', sa.JSON(), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('description_normalized', sa.Text(), nullable=False),
        sa.Column(
            'status',
            sa.Enum(
                'submitted', 'under_review', 'verified', 'rejected', name='report_status'
            ),
            server_default='submitted',
            nullable=False,
        ),
        sa.Column('is_duplicate', sa.Boolean(), server_default=sa.text('false'), nullable=False),
        sa.Column('duplicate_of_report_id', sa.Uuid(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['user_id'], ['users.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['company_id'], ['companies.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['analysis_id'], ['analyses.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['duplicate_of_report_id'], ['reports.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_reports_user_id'), 'reports', ['user_id'], unique=False)
    op.create_index(op.f('ix_reports_company_id'), 'reports', ['company_id'], unique=False)
    op.create_index(op.f('ix_reports_analysis_id'), 'reports', ['analysis_id'], unique=False)
    op.create_index(op.f('ix_reports_status'), 'reports', ['status'], unique=False)
    op.create_index(op.f('ix_reports_created_at'), 'reports', ['created_at'], unique=False)
    # Composite index backing the duplicate-detection window query
    # (`ReportRepository.find_recent_for_company`: company_id + created_at
    # range, filtered to non-duplicate rows).
    op.create_index(
        'ix_reports_company_id_created_at', 'reports', ['company_id', 'created_at'], unique=False
    )

    # --- company_signals: M8 internal-only reputation columns ---
    op.add_column(
        'company_signals',
        sa.Column('verified_report_count', sa.Integer(), server_default='0', nullable=False),
    )
    op.add_column(
        'company_signals',
        sa.Column('internal_reputation_score', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_column('company_signals', 'internal_reputation_score')
    op.drop_column('company_signals', 'verified_report_count')

    op.drop_index('ix_reports_company_id_created_at', table_name='reports')
    op.drop_index(op.f('ix_reports_created_at'), table_name='reports')
    op.drop_index(op.f('ix_reports_status'), table_name='reports')
    op.drop_index(op.f('ix_reports_analysis_id'), table_name='reports')
    op.drop_index(op.f('ix_reports_company_id'), table_name='reports')
    op.drop_index(op.f('ix_reports_user_id'), table_name='reports')
    op.drop_table('reports')

    sa.Enum(name='report_status').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='report_target_type').drop(op.get_bind(), checkfirst=True)
