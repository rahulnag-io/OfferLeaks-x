"""baseline (no tables yet)

Revision ID: 4b6f81b5fa63
Revises: 
Create Date: 2026-08-06 13:21:34.403867

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '4b6f81b5fa63'
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
