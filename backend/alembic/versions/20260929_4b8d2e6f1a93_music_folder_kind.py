"""music folder kind (music, podcasts, audiobooks)

Revision ID: 4b8d2e6f1a93
Revises: 7c1e4a9b2d30
Create Date: 2026-09-29 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "4b8d2e6f1a93"
down_revision: str | None = "7c1e4a9b2d30"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "music_folder",
        sa.Column("kind", sa.Text(), server_default=sa.text("'music'"), nullable=False),
    )


def downgrade() -> None:
    op.drop_column("music_folder", "kind")
