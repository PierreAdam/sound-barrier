"""album: description, narrator, series and number of podcasts and audiobooks

Revision ID: 2c8e6f1b4d97
Revises: 5a1d9c3e7f42
Create Date: 2026-09-30 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "2c8e6f1b4d97"
down_revision: str | None = "5a1d9c3e7f42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("album", sa.Column("description", sa.Text(), nullable=True))
    op.add_column("album", sa.Column("narrator", sa.Text(), nullable=True))
    op.add_column("album", sa.Column("series", sa.Text(), nullable=True))
    op.add_column("album", sa.Column("series_number", sa.Text(), nullable=True))
    # The details are read by the next scan: files already scanned are read again.
    op.execute(
        "UPDATE song SET file_mtime = file_mtime - interval '1 second' "
        "WHERE music_folder_id IN (SELECT id FROM music_folder WHERE kind <> 'music')"
    )


def downgrade() -> None:
    op.drop_column("album", "series_number")
    op.drop_column("album", "series")
    op.drop_column("album", "narrator")
    op.drop_column("album", "description")
