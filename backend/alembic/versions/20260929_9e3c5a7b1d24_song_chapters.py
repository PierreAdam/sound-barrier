"""chapters inside a song file (audiobooks)

Revision ID: 9e3c5a7b1d24
Revises: 4b8d2e6f1a93
Create Date: 2026-09-29 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "9e3c5a7b1d24"
down_revision: str | None = "4b8d2e6f1a93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("song", sa.Column("chapters", postgresql.JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("song", "chapters")
