"""add verdict intelligence columns and scam_patterns table

Revision ID: a1c6f9d2b3e4
Revises: 8dcf1609a3eb
Create Date: 2026-08-16 00:00:00.000000

"""
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a1c6f9d2b3e4'
down_revision: Union[str, Sequence[str], None] = '8dcf1609a3eb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Starter scam-pattern library (M6: "Scam Pattern Library" -- Revised_
# ARCHITECTURE.md M6). Deliberately small and conservative -- these are
# the clearest, lowest-false-positive signals; the set is expected to
# grow via later migrations/an admin UI (V8), not to be exhaustive here.
_SEED_PATTERNS = [
    {
        "key": "upfront_processing_fee",
        "title": "Requests an upfront payment before employment starts",
        "description": (
            "Legitimate employers do not ask candidates to pay a fee -- for "
            "equipment, training, background checks, or anything else -- "
            "before a job actually begins."
        ),
        "severity": "high",
        "keywords": [
            "processing fee",
            "registration fee",
            "training fee",
            "refundable deposit",
            "pay a fee to secure",
        ],
    },
    {
        "key": "requests_bank_details_early",
        "title": "Asks for sensitive financial details very early",
        "description": (
            "Bank account numbers, card details, or similar financial "
            "information are not something a legitimate employer needs "
            "before a formal onboarding process."
        ),
        "severity": "high",
        "keywords": [
            "bank account number",
            "routing number",
            "wire transfer details",
            "account details to proceed",
        ],
    },
    {
        "key": "free_email_domain_official",
        "title": "Uses a free personal email domain for official correspondence",
        "description": (
            "A message claiming to be an official offer letter, sent from a "
            "free consumer email address (e.g. gmail.com, yahoo.com), is a "
            "well-known impersonation pattern."
        ),
        "severity": "medium",
        "keywords": ["@gmail.com", "@yahoo.com", "@outlook.com", "@hotmail.com"],
    },
    {
        "key": "urgency_pressure_tactic",
        "title": "Uses urgency or pressure to force a fast response",
        "description": (
            "An unusually short deadline to accept, pay, or respond is a "
            "common pressure tactic meant to short-circuit normal "
            "verification."
        ),
        "severity": "medium",
        "keywords": [
            "respond within 24 hours",
            "offer expires today",
            "act immediately",
            "limited time offer",
        ],
    },
    {
        "key": "no_interview_process",
        "title": "No interview process is mentioned before the offer",
        "description": (
            "A job offer that skips any interview, screening call, or "
            "assessment step is inconsistent with how legitimate hiring "
            "normally works."
        ),
        "severity": "low",
        "keywords": [
            "no interview required",
            "no interview necessary",
            "hired without interview",
        ],
    },
]


def upgrade() -> None:
    """Upgrade schema."""
    # --- verdicts: M6 verdict-intelligence columns ---
    op.add_column(
        'verdicts',
        sa.Column(
            'matched_patterns', sa.JSON(), nullable=False, server_default='[]'
        ),
    )
    op.add_column(
        'verdicts',
        sa.Column(
            'recommended_actions', sa.JSON(), nullable=False, server_default='[]'
        ),
    )
    op.add_column(
        'verdicts',
        sa.Column(
            'evidence_coverage', sa.Float(), nullable=False, server_default='0.0'
        ),
    )

    # --- scam_patterns ---
    op.create_table(
        'scam_patterns',
        sa.Column('id', sa.Uuid(), server_default=sa.text('gen_random_uuid()'), nullable=False),
        sa.Column('key', sa.String(length=100), nullable=False),
        sa.Column('title', sa.String(length=200), nullable=False),
        sa.Column('description', sa.String(length=1000), nullable=False),
        sa.Column(
            'severity',
            sa.Enum('low', 'medium', 'high', name='scam_pattern_severity'),
            nullable=False,
        ),
        sa.Column('keywords', sa.JSON(), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_scam_patterns_key'), 'scam_patterns', ['key'], unique=True)

    scam_patterns_table = sa.table(
        'scam_patterns',
        sa.column('id', sa.Uuid()),
        sa.column('key', sa.String()),
        sa.column('title', sa.String()),
        sa.column('description', sa.String()),
        sa.column(
            'severity',
            sa.Enum('low', 'medium', 'high', name='scam_pattern_severity'),
        ),
        sa.column('keywords', sa.JSON()),
        sa.column('is_active', sa.Boolean()),
    )
    op.bulk_insert(
        scam_patterns_table,
        [
            {
                'id': uuid.uuid4(),
                'key': pattern['key'],
                'title': pattern['title'],
                'description': pattern['description'],
                'severity': pattern['severity'],
                'keywords': pattern['keywords'],
                'is_active': True,
            }
            for pattern in _SEED_PATTERNS
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_scam_patterns_key'), table_name='scam_patterns')
    op.drop_table('scam_patterns')
    sa.Enum(name='scam_pattern_severity').drop(op.get_bind(), checkfirst=True)

    op.drop_column('verdicts', 'evidence_coverage')
    op.drop_column('verdicts', 'recommended_actions')
    op.drop_column('verdicts', 'matched_patterns')
